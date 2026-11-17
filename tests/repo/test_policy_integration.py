"""The environment policy against the real demo-app manifests, as seen by the prod cluster."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.repo.helpers import ROOT

POLICY = ROOT / "gitops/platform/kyverno/policies/require-matching-env.yaml"
PROD_CONTEXT = ROOT / "tests/kyverno/context.yaml"
VALUES = ROOT / "tests/kyverno/values.yaml"


def apply_on_prod_cluster(env):
    built = subprocess.run(["kubectl", "kustomize", str(ROOT / "gitops/apps/demo-app/overlays" / env)],
                           check=True, capture_output=True, text=True).stdout
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "demo.yaml"
        manifest.write_text(built)
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
