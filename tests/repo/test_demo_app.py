"""Demo app: per-environment overlays, the promotable release file and its Application."""
import re
import subprocess
import unittest

import yaml

from tests.repo.helpers import ENVS, ROOT

APP = ROOT / "gitops/apps/demo-app"
EXPECTED = {
    "dev": {"replicas": 1, "host": "dev.k8sdemo.vn", "name": "DEV", "color": "#2e7d32"},
    "staging": {"replicas": 2, "host": "staging.k8sdemo.vn", "name": "STAGING", "color": "#f9a825"},
    "prod": {"replicas": 3, "host": "k8sdemo.vn", "name": "PRODUCTION", "color": "#c62828"},
}


def build(env):
    out = subprocess.run(["kubectl", "kustomize", str(APP / "overlays" / env)],
                         check=True, capture_output=True, text=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def one(docs, kind):
    found = [d for d in docs if d["kind"] == kind]
    assert len(found) == 1, f"expected one {kind}, got {len(found)}"
    return found[0]


class DemoOverlayTest(unittest.TestCase):
    def test_environment_specific_settings(self):
        for env, exp in EXPECTED.items():
            with self.subTest(env=env):
                docs = build(env)
                dep = one(docs, "Deployment")
                self.assertEqual(dep["spec"]["replicas"], exp["replicas"])
                c = dep["spec"]["template"]["spec"]["containers"][0]
                envs = {e["name"]: e["value"] for e in c["env"]}
                self.assertEqual(envs["ENV_NAME"], exp["name"])
                self.assertEqual(envs["ENV_COLOR"], exp["color"])
                ing = one(docs, "Ingress")
                self.assertEqual(ing["spec"]["ingressClassName"], "nginx")
                self.assertEqual([r["host"] for r in ing["spec"]["rules"]], [exp["host"]])

    def test_every_resource_carries_the_environment_label(self):
        for env in ENVS:
            with self.subTest(env=env):
                for d in build(env):
                    self.assertEqual(d["metadata"].get("labels", {}).get("k8sdemo.vn/env"), env,
                                     f"{d['kind']}/{d['metadata']['name']}")

    def test_namespace_is_managed_by_the_environment_policy(self):
        ns = one(build("prod"), "Namespace")
        self.assertEqual(ns["metadata"]["name"], "demo")
        self.assertEqual(ns["metadata"]["labels"]["k8sdemo.vn/managed"], "true")

    def test_page_template_change_rolls_the_pods(self):
        docs = build("prod")
        cm = one(docs, "ConfigMap")
        self.assertRegex(cm["metadata"]["name"], r"^demo-page-template-[a-z0-9]{10}$")
        vols = one(docs, "Deployment")["spec"]["template"]["spec"]["volumes"]
        self.assertIn(cm["metadata"]["name"], [v["configMap"]["name"] for v in vols if "configMap" in v])

    def test_pod_spec_basics(self):
        spec = one(build("prod"), "Deployment")["spec"]["template"]["spec"]
        c = spec["containers"][0]
        self.assertEqual(c["image"], "nginx:1.31.8-alpine")
        self.assertEqual(c["readinessProbe"]["httpGet"]["path"], "/healthz")
        self.assertEqual(c["resources"]["requests"], {"cpu": "10m", "memory": "16Mi"})
        self.assertEqual(c["resources"]["limits"], {"memory": "64Mi"})
        term = spec["affinity"]["podAntiAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"][0]
        self.assertEqual(term["podAffinityTerm"]["topologyKey"], "kubernetes.io/hostname")


class ReleaseFileTest(unittest.TestCase):
    """release.yaml is the only promotable file, so it must contain nothing environment-specific."""

    def test_release_file_is_environment_neutral(self):
        for env in ENVS:
            with self.subTest(env=env):
                text = (APP / "overlays" / env / "release.yaml").read_text()
                self.assertIsNone(re.search(r"(?i)\b(dev|staging|prod|production|replicas)\b|k8sdemo", text))

    def test_release_file_only_sets_image_version_and_message(self):
        for env in ENVS:
            with self.subTest(env=env):
                patch = yaml.safe_load((APP / "overlays" / env / "release.yaml").read_text())
                c = patch["spec"]["template"]["spec"]["containers"][0]
                self.assertEqual(set(c), {"name", "image", "env"})
                names = [e["name"] for e in c["env"]]
                self.assertEqual(names, ["APP_VERSION", "APP_MESSAGE"])
                message = c["env"][1]["value"]
                self.assertIsNone(re.search(r"['$\\;{}]", message), "message would break the nginx config")


class DemoApplicationTest(unittest.TestCase):
    def test_application(self):
        for env in ENVS:
            with self.subTest(env=env):
                a = yaml.safe_load((ROOT / f"gitops/clusters/{env}/demo-app.yaml").read_text())
                self.assertEqual(a["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "6")
                self.assertEqual(a["spec"]["source"]["path"], f"gitops/apps/demo-app/overlays/{env}")
                self.assertEqual(a["spec"]["destination"]["namespace"], "demo")


if __name__ == "__main__":
    unittest.main()
