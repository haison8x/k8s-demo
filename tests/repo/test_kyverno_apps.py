"""Kyverno engine and policy Applications."""
import unittest

import yaml

from tests.repo.helpers import ENVS, ROOT

REPO = "https://github.com/haison8x/k8s-demo.git"


def app(env, name):
    return yaml.safe_load((ROOT / f"gitops/clusters/{env}/{name}.yaml").read_text())


class KyvernoAppsTest(unittest.TestCase):
    def test_engine_application(self):
        for env in ENVS:
            with self.subTest(env=env):
                a = app(env, "kyverno")
                self.assertEqual(a["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "2")
                chart = a["spec"]["sources"][0]
                self.assertEqual((chart["repoURL"], chart["chart"], chart["targetRevision"]),
                                 ("https://kyverno.github.io/kyverno/", "kyverno", "3.10.0"))
                self.assertEqual(chart["helm"]["valueFiles"], ["$values/gitops/platform/kyverno/values.yaml"])
                self.assertEqual(a["spec"]["destination"]["namespace"], "kyverno")
                opts = a["spec"]["syncPolicy"]["syncOptions"]
                self.assertIn("CreateNamespace=true", opts)
                self.assertIn("ServerSideApply=true", opts)

    def test_policies_application_is_identical_in_every_environment(self):
        apps = [app(env, "kyverno-policies") for env in ENVS]
        for a in apps:
            self.assertEqual(a["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "3")
            self.assertEqual(a["spec"]["source"]["path"], "gitops/platform/kyverno/policies")
            self.assertEqual(a["spec"]["source"]["repoURL"], REPO)
            self.assertIn("SkipDryRunOnMissingResource=true", a["spec"]["syncPolicy"]["syncOptions"])
        self.assertEqual(apps[0]["spec"], apps[1]["spec"])
        self.assertEqual(apps[1]["spec"], apps[2]["spec"])

    def test_policy_reads_the_cluster_identity(self):
        pol = yaml.safe_load((ROOT / "gitops/platform/kyverno/policies/require-matching-env.yaml").read_text())
        self.assertEqual((pol["apiVersion"], pol["kind"]), ("policies.kyverno.io/v1", "ValidatingPolicy"))
        spec = pol["spec"]
        self.assertEqual(spec["validationActions"], ["Deny"])
        self.assertEqual(spec["failurePolicy"], "Fail")
        cluster_env = next(v for v in spec["variables"] if v["name"] == "clusterEnv")["expression"]
        self.assertIn('"kube-system", "cluster-identity"', cluster_env)
        sel = spec["matchConstraints"]["namespaceSelector"]["matchLabels"]
        self.assertEqual(sel, {"k8sdemo.vn/managed": "true"})


if __name__ == "__main__":
    unittest.main()
