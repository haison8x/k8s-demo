"""Every GitOps manifest renders with kustomize and validates against Kubernetes/CRD schemas."""
import subprocess
import unittest

from tests.repo.helpers import ENVS, ROOT

GITOPS = ROOT / "gitops"
CRD_SCHEMAS = ("https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/"
               "{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json")
# Upstream CRD definitions (e.g. Argo CD's) have no schema in the catalogs; they are not authored here.
KUBECONFORM = ["kubeconform", "-strict", "-summary", "-skip", "CustomResourceDefinition",
               "-schema-location", "default", "-schema-location", CRD_SCHEMAS]


def kustomize_dirs():
    return sorted(p.parent for p in GITOPS.rglob("kustomization.yaml"))


def kubeconform(text, label):
    res = subprocess.run(KUBECONFORM + ["-"], input=text, capture_output=True, text=True)
    if res.returncode != 0:
        raise AssertionError(f"kubeconform failed for {label}:\n{res.stdout[-3000:]}{res.stderr[-1000:]}")


class GitopsSchemaTest(unittest.TestCase):
    def test_expected_entry_points_exist(self):
        for env in ENVS:
            self.assertTrue((GITOPS / "platform/argocd/overlays" / env / "kustomization.yaml").exists())
            self.assertTrue((GITOPS / "clusters" / env / "argocd.yaml").exists())

    def test_every_kustomization_builds_and_validates(self):
        dirs = kustomize_dirs()
        self.assertTrue(dirs)
        for d in dirs:
            with self.subTest(dir=str(d.relative_to(ROOT))):
                built = subprocess.run(["kubectl", "kustomize", str(d)], capture_output=True, text=True)
                self.assertEqual(built.returncode, 0, built.stderr[-2000:])
                kubeconform(built.stdout, d.relative_to(ROOT))

    def test_every_application_validates(self):
        files = sorted((GITOPS / "clusters").glob("*/*.yaml"))
        self.assertTrue(files)
        for f in files:
            with self.subTest(file=str(f.relative_to(ROOT))):
                kubeconform(f.read_text(), f.relative_to(ROOT))


if __name__ == "__main__":
    unittest.main()
