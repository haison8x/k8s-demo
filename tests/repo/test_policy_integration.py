"""The environment policy against the real demo-app manifests, as seen by the prod cluster."""
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.repo.helpers import ROOT, app_values, helm_template

POLICY = ROOT / "gitops/platform/kyverno/policies/require-matching-env.yaml"
PROD_CONTEXT = ROOT / "tests/kyverno/context.yaml"
VALUES = ROOT / "tests/kyverno/values.yaml"


def namespace_created_by_argocd(env):
    """The Namespace Argo CD creates from the Application's managedNamespaceMetadata."""
    app = yaml.safe_load((ROOT / f"gitops/clusters/{env}/demo-app.yaml").read_text())
    labels = app["spec"]["syncPolicy"]["managedNamespaceMetadata"]["labels"]
    return yaml.safe_dump({"apiVersion": "v1", "kind": "Namespace",
                           "metadata": {"name": app["spec"]["destination"]["namespace"], "labels": labels}})


def apply_on_prod_cluster(env):
    built = helm_template(app_values("demo-app", env), release="demo-app", namespace="demo").stdout
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "demo.yaml"
        manifest.write_text(namespace_created_by_argocd(env) + "---\n" + built)
        return subprocess.run(["kyverno", "apply", str(POLICY), "-r", str(manifest),
                               "--context-file", str(PROD_CONTEXT), "-f", str(VALUES)],
                              capture_output=True, text=True)


class PolicyIntegrationTest(unittest.TestCase):
    def test_prod_manifests_are_admitted_on_prod(self):
        res = apply_on_prod_cluster("prod")
        self.assertEqual(res.returncode, 0, res.stdout[-2000:])
        self.assertIn("pass: 4, fail: 0", res.stdout)

    def test_dev_manifests_are_rejected_on_prod(self):
        res = apply_on_prod_cluster("dev")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("pass: 0, fail: 4", res.stdout)


if __name__ == "__main__":
    unittest.main()
