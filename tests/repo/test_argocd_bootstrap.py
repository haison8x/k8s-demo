"""ArgoCD bootstrap: root Application and per-environment ArgoCD overlay settings."""
import unittest

import yaml

from tests.repo.helpers import ENVS, ROOT, rendered

BANNERS = {"dev": "DEV", "staging": "STAGING", "prod": "PRODUCTION"}
ARGOCD_HOSTS = {"dev": "argocd.dev.k8sdemo.vn", "staging": "argocd.staging.k8sdemo.vn",
                "prod": "argocd.k8sdemo.vn"}


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


class RootApplicationTest(unittest.TestCase):
    def test_root_application_points_at_the_environment_folder(self):
        for env in ENVS:
            with self.subTest(env=env):
                app = yaml.safe_load(rendered(env, "root-app.yaml"))
                self.assertEqual(app["kind"], "Application")
                self.assertEqual(app["metadata"]["name"], "root")
                self.assertEqual(app["metadata"]["namespace"], "argocd")
                src = app["spec"]["source"]
                self.assertEqual(src["repoURL"], "https://github.com/haison8x/k8s-demo.git")
                self.assertEqual(src["targetRevision"], "main")
                self.assertEqual(src["path"], f"gitops/clusters/{env}")
                self.assertEqual(app["spec"]["syncPolicy"]["automated"], {"prune": True, "selfHeal": True})


class ArgocdOverlayTest(unittest.TestCase):
    def test_banner_insecure_mode_and_ingress_host(self):
        for env in ENVS:
            with self.subTest(env=env):
                base = f"gitops/platform/argocd/overlays/{env}"
                cm = load(f"{base}/argocd-cm.yaml")
                self.assertEqual(cm["data"]["ui.bannercontent"], BANNERS[env])
                self.assertEqual(cm["data"]["ui.bannerpermanent"], "true")
                params = load(f"{base}/argocd-cmd-params-cm.yaml")
                self.assertEqual(params["data"]["server.insecure"], "true")
                ing = load(f"{base}/ingress.yaml")
                self.assertEqual(ing["spec"]["ingressClassName"], "nginx")
                rule = ing["spec"]["rules"][0]
                self.assertEqual(rule["host"], ARGOCD_HOSTS[env])
                backend = rule["http"]["paths"][0]["backend"]["service"]
                self.assertEqual(backend, {"name": "argocd-server", "port": {"number": 80}})

    def test_argocd_application_is_wave_5(self):
        for env in ENVS:
            app = load(f"gitops/clusters/{env}/argocd.yaml")
            self.assertEqual(app["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "5")

    def test_base_pins_the_argocd_version(self):
        k = (ROOT / "gitops/platform/argocd/base/kustomization.yaml").read_text()
        self.assertIn("argoproj/argo-cd/v3.6.1/manifests/install.yaml", k)


if __name__ == "__main__":
    unittest.main()
