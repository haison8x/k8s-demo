"""gitops/charts/base-app: the shared chart every application is rendered with."""
import unittest

import yaml

from tests.repo.helpers import CHART, ROOT, helm_template
from tests.repo.test_gitops_schemas import kubeconform

MINIMAL = ["environment=dev", "image.repository=example/app", "image.tag=1.0"]
FULL = MINIMAL + ["ingress.enabled=true", "ingress.host=app.dev.k8sdemo.vn", "probes.path=/healthz",
                  "autoscaling.enabled=true", "podDisruptionBudget.enabled=true",
                  "env.GREETING=hello", "files.app\.conf=x=1"]


def render(sets, **kw):
    out = helm_template(sets=sets, **kw).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def kinds(docs):
    return sorted(d["kind"] for d in docs)


def one(docs, kind):
    found = [d for d in docs if d["kind"] == kind]
    assert len(found) == 1, f"expected one {kind}, got {len(found)}"
    return found[0]


class BaseChartTest(unittest.TestCase):
    def test_chart_metadata(self):
        chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
        self.assertEqual(chart["name"], "base-app")
        self.assertEqual(chart["apiVersion"], "v2")
        self.assertEqual(chart["type"], "application")

    def test_minimal_values_render_a_deployment_and_a_service(self):
        docs = render(MINIMAL)
        self.assertEqual(kinds(docs), ["Deployment", "Service"])
        dep = one(docs, "Deployment")
        self.assertEqual(dep["metadata"]["name"], "app")
        self.assertEqual(dep["spec"]["template"]["spec"]["containers"][0]["image"], "example/app:1.0")

    def test_optional_features_render_when_enabled(self):
        docs = render(FULL)
        self.assertEqual(kinds(docs), ["ConfigMap", "Deployment", "HorizontalPodAutoscaler",
                                       "Ingress", "PodDisruptionBudget", "Service"])
        self.assertNotIn("replicas", one(docs, "Deployment")["spec"], "the autoscaler owns the replica count")

    def test_every_resource_and_pod_carries_the_environment_label(self):
        for d in render(FULL):
            self.assertEqual(d["metadata"]["labels"]["k8sdemo.vn/env"], "dev", d["kind"])
        pod = one(render(FULL), "Deployment")["spec"]["template"]["metadata"]["labels"]
        self.assertEqual(pod["k8sdemo.vn/env"], "dev")

    def test_every_resource_is_placed_in_the_release_namespace(self):
        for d in render(FULL, namespace="shop"):
            self.assertEqual(d["metadata"]["namespace"], "shop", d["kind"])

    def test_environment_is_required_and_checked(self):
        res = helm_template(sets=["image.repository=example/app", "image.tag=1.0"], check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("environment is required", res.stderr)
        res = helm_template(sets=["environment=qa", "image.repository=example/app", "image.tag=1.0"], check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("environment must be one of dev, staging, prod", res.stderr)

    def test_image_is_required(self):
        res = helm_template(sets=["environment=dev"], check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("image.repository is required", res.stderr)

    def test_environment_variables_from_several_values_files_merge(self):
        docs = render(MINIMAL + ["env.A=1", "env.B=two"])
        c = one(docs, "Deployment")["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(c["env"], [{"name": "A", "value": "1"}, {"name": "B", "value": "two"}])

    def test_changing_a_file_rolls_the_pods(self):
        def checksum(content):
            dep = one(render(MINIMAL + [f"files.app\.conf={content}"]), "Deployment")
            return dep["spec"]["template"]["metadata"]["annotations"]["checksum/files"]
        self.assertNotEqual(checksum("a"), checksum("b"))

    def test_files_are_mounted_from_the_config_map(self):
        docs = render(MINIMAL + ["files.app\.conf=x", "filesMountPath=/etc/app"])
        cm = one(docs, "ConfigMap")
        spec = one(docs, "Deployment")["spec"]["template"]["spec"]
        self.assertEqual(cm["data"], {"app.conf": "x"})
        self.assertEqual(spec["volumes"][0]["configMap"]["name"], cm["metadata"]["name"])
        self.assertEqual(spec["containers"][0]["volumeMounts"][0]["mountPath"], "/etc/app")

    def test_pods_spread_across_nodes_by_default(self):
        spec = one(render(MINIMAL), "Deployment")["spec"]["template"]["spec"]
        term = spec["affinity"]["podAntiAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"][0]
        self.assertEqual(term["podAffinityTerm"]["topologyKey"], "kubernetes.io/hostname")
        self.assertNotIn("affinity", one(render(MINIMAL + ["podAntiAffinity=none"]), "Deployment")["spec"]["template"]["spec"])

    def test_toolchain_and_ci_cover_the_chart(self):
        tools = (ROOT / "scripts/install-tools.sh").read_text()
        self.assertRegex(tools, r"HELM_VERSION=v\d+\.\d+\.\d+")
        validate = (ROOT / "scripts/validate.sh").read_text()
        self.assertIn("helm lint --strict", validate)
        smoke = (ROOT / "scripts/smoke-demo-page.sh").read_text()
        self.assertIn("helm template", smoke)
        self.assertIn("gitops/charts/*/templates/", (ROOT / ".yamllint").read_text())

    def test_rendered_resources_match_the_kubernetes_schemas(self):
        kubeconform(helm_template(sets=FULL).stdout, "base-app with every feature enabled")


if __name__ == "__main__":
    unittest.main()
