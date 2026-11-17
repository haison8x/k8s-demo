"""scripts/env-guard.py check-tree: cross-checks between inventories and GitOps files."""
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.repo.helpers import ROOT

GUARD = ROOT / "scripts" / "env-guard.py"
NETS = {"dev": "172.20.2", "staging": "172.20.1", "prod": "172.20.0"}
HOSTS = {"dev": "dev.k8sdemo.vn", "staging": "staging.k8sdemo.vn", "prod": "k8sdemo.vn"}
PROXY = "http://proxy.mycompany.com:3128"
REPO = "https://github.com/haison8x/k8s-demo.git"


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text).lstrip(), newline="\n")


def no_proxy(env):
    net = NETS[env]
    return f"localhost,127.0.0.1,{net}.0/24,{net}.100,10.244.0.0/16,10.96.0.0/12,.svc,.cluster.local,.k8sdemo.vn"


def build_tree(root, overrides=None):
    """A minimal, correct repository tree; `overrides` maps relative paths to new text."""
    for env, net in NETS.items():
        write(root, f"ansible/inventories/{env}/group_vars/all.yml", f"""
            env: {env}
            env_subnet: {net}.0/24
            kube_vip_address: {net}.100
            metallb_range_start: {net}.200
            metallb_range_end: {net}.229
            ingress_ip: {net}.200
            proxy_http: {PROXY}
            proxy_https: {PROXY}
            proxy_no_proxy: {no_proxy(env)}
            argocd_root_path: gitops/clusters/{env}
            app_host: {HOSTS[env]}
            argocd_host: argocd.{HOSTS[env]}
            """)
        write(root, f"gitops/clusters/{env}/argocd.yaml", f"""
            apiVersion: argoproj.io/v1alpha1
            kind: Application
            metadata:
              name: argocd
              namespace: argocd
            spec:
              project: default
              source:
                repoURL: {REPO}
                targetRevision: main
                path: gitops/platform/argocd/overlays/{env}
              destination:
                server: https://kubernetes.default.svc
                namespace: argocd
              syncPolicy:
                automated:
                  prune: true
                  selfHeal: true
            """)
        write(root, f"gitops/platform/argocd/overlays/{env}/proxy-env-repo-server.yaml", f"""
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: argocd-repo-server
            spec:
              template:
                spec:
                  containers:
                    - name: argocd-repo-server
                      env:
                        - name: HTTP_PROXY
                          value: {PROXY}
                        - name: HTTPS_PROXY
                          value: {PROXY}
                        - name: NO_PROXY
                          value: {no_proxy(env)},argocd-repo-server
            """)
        write(root, f"gitops/platform/metallb/config/overlays/{env}/ip-pool.yaml", f"""
            apiVersion: metallb.io/v1beta1
            kind: IPAddressPool
            metadata:
              name: demo-pool
            spec:
              addresses:
                - {net}.200-{net}.229
            """)
        write(root, f"gitops/platform/nginx-ingress/values-{env}.yaml", f"""
            controller:
              service:
                annotations:
                  metallb.io/loadBalancerIPs: {net}.200
            """)
        write(root, f"gitops/platform/argocd/overlays/{env}/ingress.yaml", f"""
            apiVersion: networking.k8s.io/v1
            kind: Ingress
            metadata:
              name: argocd-server
            spec:
              rules:
                - host: argocd.{HOSTS[env]}
            """)
        write(root, f"gitops/clusters/{env}/demo-app.yaml", f"""
            apiVersion: argoproj.io/v1alpha1
            kind: Application
            metadata:
              name: demo-app
              namespace: argocd
            spec:
              project: default
              sources:
                - repoURL: {REPO}
                  targetRevision: main
                  path: gitops/charts/base-app
                  helm:
                    valueFiles:
                      - $values/gitops/apps/demo-app/values.yaml
                      - $values/gitops/apps/demo-app/envs/{env}/env.yaml
                      - $values/gitops/apps/demo-app/envs/{env}/release.yaml
                - repoURL: {REPO}
                  targetRevision: main
                  ref: values
              destination:
                server: https://kubernetes.default.svc
                namespace: demo
              syncPolicy:
                automated:
                  prune: true
                  selfHeal: true
            """)
        write(root, f"gitops/apps/demo-app/envs/{env}/env.yaml", f"""
            environment: {env}
            ingress:
              host: {HOSTS[env]}
            """)
    for rel, text in (overrides or {}).items():
        write(root, rel, text)


def run_guard(root):
    return subprocess.run([sys.executable, str(GUARD), "check-tree", "--root", str(root)],
                          capture_output=True, text=True)


class CheckTreeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_correct_tree_passes(self):
        build_tree(self.root)
        res = run_guard(self.root)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_prod_application_pointing_at_dev_overlay_fails(self):
        build_tree(self.root)
        p = self.root / "gitops/clusters/prod/argocd.yaml"
        p.write_text(p.read_text().replace("overlays/prod", "overlays/dev"), newline="\n")
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("prod application argocd points at dev path", res.stdout)

    def test_proxy_mismatch_fails(self):
        build_tree(self.root)
        p = self.root / "gitops/platform/argocd/overlays/staging/proxy-env-repo-server.yaml"
        p.write_text(p.read_text().replace(PROXY, "http://other-proxy:8080"), newline="\n")
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("proxy mismatch", res.stdout)

    def test_missing_no_proxy_entry_fails(self):
        build_tree(self.root)
        p = self.root / "gitops/platform/argocd/overlays/dev/proxy-env-repo-server.yaml"
        p.write_text(p.read_text().replace(",.svc", ""), newline="\n")
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("NO_PROXY", res.stdout)

    def test_ingress_host_of_another_environment_fails(self):
        build_tree(self.root)
        p = self.root / "gitops/platform/argocd/overlays/dev/ingress.yaml"
        p.write_text(p.read_text().replace("argocd.dev.k8sdemo.vn", "argocd.k8sdemo.vn"), newline="\n")
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("host argocd.k8sdemo.vn", res.stdout)

    def test_application_without_self_heal_fails(self):
        build_tree(self.root)
        p = self.root / "gitops/clusters/dev/argocd.yaml"
        p.write_text(p.read_text().replace("selfHeal: true", "selfHeal: false"), newline="\n")
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("automated prune and selfHeal", res.stdout)


    def test_metallb_pool_of_another_environment_fails(self):
        build_tree(self.root)
        p = self.root / "gitops/platform/metallb/config/overlays/staging/ip-pool.yaml"
        p.write_text(p.read_text().replace("172.20.1.", "172.20.0."), newline="\n")
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("staging: MetalLB pool", res.stdout)

    def test_ingress_load_balancer_ip_mismatch_fails(self):
        build_tree(self.root)
        p = self.root / "gitops/platform/nginx-ingress/values-prod.yaml"
        p.write_text(p.read_text().replace("172.20.0.200", "172.20.0.201"), newline="\n")
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("prod: ingress loadBalancerIPs", res.stdout)

    def test_app_values_of_another_environment_fail(self):
        build_tree(self.root)
        p = self.root / "gitops/clusters/prod/demo-app.yaml"
        p.write_text(p.read_text().replace("envs/prod/", "envs/dev/"), newline="\n")
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("prod application demo-app points at dev path", res.stdout)

    def test_app_env_file_declaring_another_environment_fails(self):
        build_tree(self.root)
        p = self.root / "gitops/apps/demo-app/envs/staging/env.yaml"
        p.write_text(p.read_text().replace("environment: staging", "environment: prod"), newline="\n")
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("staging: gitops/apps/demo-app/envs/staging/env.yaml declares environment prod", res.stdout)

    def test_app_ingress_host_of_another_environment_fails(self):
        build_tree(self.root)
        p = self.root / "gitops/apps/demo-app/envs/dev/env.yaml"
        p.write_text(p.read_text().replace("host: dev.k8sdemo.vn", "host: k8sdemo.vn"), newline="\n")
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("uses host k8sdemo.vn", res.stdout)


    def test_new_app_host_under_the_environment_domain_passes(self):
        build_tree(self.root, {"gitops/apps/shop/envs/dev/env.yaml": """
            environment: dev
            ingress:
              host: shop.dev.k8sdemo.vn
            """})
        res = run_guard(self.root)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_new_app_host_under_another_environment_domain_fails(self):
        for host in ("shop.k8sdemo.vn", "shop.staging.k8sdemo.vn"):
            with self.subTest(host=host):
                build_tree(self.root, {"gitops/apps/shop/envs/dev/env.yaml": f"""
                    environment: dev
                    ingress:
                      host: {host}
                    """})
                res = run_guard(self.root)
                self.assertNotEqual(res.returncode, 0)
                self.assertIn(f"uses host {host}", res.stdout)

    def test_prod_app_host_must_not_sit_under_another_environment(self):
        build_tree(self.root, {"gitops/apps/shop/envs/prod/env.yaml": """
            environment: prod
            ingress:
              host: shop.dev.k8sdemo.vn
            """})
        res = run_guard(self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("uses host shop.dev.k8sdemo.vn", res.stdout)


class RealTreeTest(unittest.TestCase):
    def test_repository_passes_check_tree(self):
        res = run_guard(ROOT)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
