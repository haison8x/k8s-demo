#!/usr/bin/env python3
"""Environment guard: catches changes that would mix up dev, staging and prod.

  env-guard.py check-tree [--root DIR]
      Cross-checks the repository: every cluster's Applications point only at
      that environment's paths, each app's envs/<env>/env.yaml names its own
      environment, ingress hosts and proxy settings match the environment's
      inventory.

  env-guard.py check-diff BASE_REF [--root DIR]
      Fails when the changes since BASE_REF touch more than one environment
      (promotion happens one environment at a time). Shared paths such as
      gitops/charts/, roles and workflows do not count; CODEOWNERS reviews them.

Exits 1 and prints one line per problem.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import yaml

ENVS = ("dev", "staging", "prod")
REPO_URL = "https://github.com/haison8x/k8s-demo.git"
SHARED_PATHS = ("gitops/platform/kyverno/policies",)
SHARED_PREFIXES = ("gitops/charts/",)


def load_all(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]


def inventory_vars(root, env):
    return yaml.safe_load((root / "ansible/inventories" / env / "group_vars/all.yml").read_text())


def env_in_path(path):
    """Return the environment a path is specific to, or None if shared."""
    parts = path.replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        if part in ("overlays", "envs", "clusters", "inventories") and i + 1 < len(parts) and parts[i + 1] in ENVS:
            return parts[i + 1]
        for env in ENVS:
            if part == f"values-{env}.yaml":
                return env
    return None


def application_sources(app):
    spec = app.get("spec", {})
    return spec.get("sources") or ([spec["source"]] if "source" in spec else [])


def check_applications(root, env, problems):
    for f in sorted((root / "gitops/clusters" / env).glob("*.yaml")):
        for app in load_all(f):
            if app.get("kind") != "Application":
                continue
            name = app["metadata"]["name"]
            automated = (app["spec"].get("syncPolicy") or {}).get("automated") or {}
            if not (automated.get("prune") is True and automated.get("selfHeal") is True):
                problems.append(f"{env} application {name} must enable automated prune and selfHeal")
            for src in application_sources(app):
                paths = [src["path"]] if "path" in src else []
                paths += [v.replace("$values/", "") for v in (src.get("helm") or {}).get("valueFiles", [])]
                if src.get("repoURL") == REPO_URL and src.get("targetRevision") != "main":
                    problems.append(f"{env} application {name} must track targetRevision main")
                for p in paths:
                    other = env_in_path(p)
                    if other and other != env:
                        problems.append(f"{env} application {name} points at {other} path {p}")
                    elif other is None and "path" in src and p == src["path"] and not (
                            p.endswith("/base") or p in SHARED_PATHS or p.startswith(SHARED_PREFIXES)):
                        problems.append(f"{env} application {name} uses non-environment path {p}")


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def host_allowed(host, inv):
    """The environment's own hosts, or one label directly under its app host
    (shop.dev.k8sdemo.vn in dev, shop.k8sdemo.vn in prod)."""
    if host in (inv["app_host"], inv["argocd_host"]):
        return True
    suffix = "." + inv["app_host"]
    return host.endswith(suffix) and "." not in host[: -len(suffix)] and host != suffix


def check_ingress_hosts(root, env, inv, problems):
    allowed = {inv["app_host"], inv["argocd_host"], "*." + inv["app_host"]}
    files = list(root.glob(f"gitops/**/overlays/{env}/*.yaml")) + list(root.glob(f"gitops/apps/*/envs/{env}/*.yaml"))
    for f in sorted(files):
        for doc in load_all(f):
            for node in walk(doc):
                host = node.get("host")
                if isinstance(host, str) and not host_allowed(host, inv):
                    problems.append(f"{env}: {f.relative_to(root)} uses host {host}, allowed {sorted(allowed)}")


def check_app_env_files(root, env, problems):
    for f in sorted(root.glob(f"gitops/apps/*/envs/{env}/env.yaml")):
        declared = (load_all(f) or [{}])[0].get("environment")
        if declared != env:
            problems.append(f"{env}: {f.relative_to(root).as_posix()} declares environment {declared}")


def check_proxy(root, env, inv, problems):
    required_no_proxy = set(inv["proxy_no_proxy"].split(","))
    expected = {"HTTP_PROXY": inv["proxy_http"], "HTTPS_PROXY": inv["proxy_https"]}
    for f in sorted((root / "gitops/platform/argocd/overlays" / env).glob("proxy-env-*.yaml")):
        for doc in load_all(f):
            for c in doc["spec"]["template"]["spec"]["containers"]:
                values = {e["name"]: e.get("value", "") for e in c.get("env", [])}
                for key, want in expected.items():
                    if values.get(key) != want:
                        problems.append(f"{env}: proxy mismatch in {f.name}: {key}={values.get(key)!r}, inventory says {want!r}")
                missing = required_no_proxy - set(values.get("NO_PROXY", "").split(","))
                if missing:
                    problems.append(f"{env}: NO_PROXY in {f.name} is missing {sorted(missing)}")


def check_addresses(root, env, inv, problems):
    want_pool = f"{inv['metallb_range_start']}-{inv['metallb_range_end']}"
    pool_file = root / "gitops/platform/metallb/config/overlays" / env / "ip-pool.yaml"
    if pool_file.exists():
        addresses = load_all(pool_file)[0]["spec"]["addresses"]
        if addresses != [want_pool]:
            problems.append(f"{env}: MetalLB pool {addresses} does not match inventory range {want_pool}")
    values_file = root / "gitops/platform/nginx-ingress" / f"values-{env}.yaml"
    if values_file.exists():
        ann = load_all(values_file)[0]["controller"]["service"]["annotations"]
        ip = ann.get("metallb.io/loadBalancerIPs")
        if ip != inv["ingress_ip"]:
            problems.append(f"{env}: ingress loadBalancerIPs {ip} does not match inventory ingress_ip {inv['ingress_ip']}")


def check_tree(root):
    problems = []
    for env in ENVS:
        inv = inventory_vars(root, env)
        if inv.get("env") != env:
            problems.append(f"inventory {env} declares env {inv.get('env')!r}")
        check_applications(root, env, problems)
        check_app_env_files(root, env, problems)
        check_ingress_hosts(root, env, inv, problems)
        check_proxy(root, env, inv, problems)
        check_addresses(root, env, inv, problems)
    return problems


def check_diff(root, base_ref):
    changed = subprocess.run(["git", "-C", str(root), "diff", "--name-only", f"{base_ref}...HEAD"],
                             check=True, capture_output=True, text=True).stdout.split()
    envs = sorted({e for e in map(env_in_path, changed) if e}, key=ENVS.index)
    if len(envs) > 1:
        return [f"this change touches more than one environment: {', '.join(envs)} "
                f"- split it into one pull request per environment"]
    return []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    default_root = Path(__file__).resolve().parents[1]
    tree = sub.add_parser("check-tree", help="cross-check the repository tree")
    tree.add_argument("--root", type=Path, default=default_root)
    diff = sub.add_parser("check-diff", help="reject changes spanning several environments")
    diff.add_argument("base_ref")
    diff.add_argument("--root", type=Path, default=default_root)
    args = parser.parse_args(argv)

    problems = check_tree(args.root) if args.command == "check-tree" else check_diff(args.root, args.base_ref)
    for p in problems:
        print(f"env-guard: {p}")
    if problems:
        return 1
    print("env-guard: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
