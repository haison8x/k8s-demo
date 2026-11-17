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
        write(root, f"gitops/platform/argocd/overlays/{env}/ingress.yaml", f"""
            apiVersion: networking.k8s.io/v1
            kind: Ingress
            metadata:
              name: argocd-server
            spec:
              rules:
                - host: argocd.{HOSTS[env]}
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


class RealTreeTest(unittest.TestCase):
    def test_repository_passes_check_tree(self):
        res = run_guard(ROOT)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
