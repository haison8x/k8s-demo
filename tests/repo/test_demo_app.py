"""Demo app: rendered with the base-app chart from per-environment values files."""
import re
import unittest

import yaml

from tests.repo.helpers import APPS, ENVS, ROOT, app_values, helm_template

APP = APPS / "demo-app"
EXPECTED = {
    "dev": {"replicas": 1, "host": "dev.k8sdemo.vn", "name": "DEV", "color": "#2e7d32"},
    "staging": {"replicas": 2, "host": "staging.k8sdemo.vn", "name": "STAGING", "color": "#f9a825"},
    "prod": {"replicas": 3, "host": "k8sdemo.vn", "name": "PRODUCTION", "color": "#c62828"},
}


def build(env, sets=()):
    out = helm_template(app_values("demo-app", env), sets=sets, release="demo-app", namespace="demo").stdout
    return [d for d in yaml.safe_load_all(out) if d]


def one(docs, kind):
    found = [d for d in docs if d["kind"] == kind]
    assert len(found) == 1, f"expected one {kind}, got {len(found)}"
    return found[0]


def container_env(docs):
    c = one(docs, "Deployment")["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e["value"] for e in c["env"]}


class DemoAppTest(unittest.TestCase):
    def test_kustomize_layout_is_gone(self):
        self.assertFalse((APP / "base").exists())
        self.assertFalse((APP / "overlays").exists())

    def test_environment_specific_settings(self):
        for env, exp in EXPECTED.items():
            with self.subTest(env=env):
                docs = build(env)
                dep = one(docs, "Deployment")
                self.assertEqual(dep["metadata"]["name"], "demo-app")
                self.assertEqual(dep["spec"]["replicas"], exp["replicas"])
                envs = container_env(docs)
                self.assertEqual(envs["ENV_NAME"], exp["name"])
                self.assertEqual(envs["ENV_COLOR"], exp["color"])
                ing = one(docs, "Ingress")
                self.assertEqual(ing["spec"]["ingressClassName"], "nginx")
                self.assertEqual([r["host"] for r in ing["spec"]["rules"]], [exp["host"]])

    def test_release_variables_reach_the_container(self):
        envs = container_env(build("prod"))
        self.assertEqual(envs["APP_VERSION"], "1.0.0")
        self.assertEqual(envs["APP_MESSAGE"], "Hello from GitOps")

    def test_every_resource_carries_the_environment_label(self):
        for env in ENVS:
            with self.subTest(env=env):
                for d in build(env):
                    self.assertEqual(d["metadata"]["labels"]["k8sdemo.vn/env"], env,
                                     f"{d['kind']}/{d['metadata']['name']}")

    def test_page_template_is_mounted_where_nginx_reads_templates(self):
        docs = build("prod")
        cm = one(docs, "ConfigMap")
        self.assertIn("default.conf.template", cm["data"])
        self.assertIn("K8s Demo", cm["data"]["default.conf.template"])
        c = one(docs, "Deployment")["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(c["volumeMounts"][0]["mountPath"], "/etc/nginx/templates")

    def test_pod_spec_basics(self):
        spec = one(build("prod"), "Deployment")["spec"]["template"]["spec"]
        c = spec["containers"][0]
        self.assertEqual(c["name"], "nginx")
        self.assertEqual(c["image"], "nginx:1.31.8-alpine")
        self.assertEqual(c["ports"][0]["containerPort"], 80)
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
                text = (APP / "envs" / env / "release.yaml").read_text()
                self.assertIsNone(re.search(r"(?i)\b(dev|staging|prod|production|replicas)\b|k8sdemo", text))

    def test_release_file_only_sets_image_tag_version_and_message(self):
        for env in ENVS:
            with self.subTest(env=env):
                values = yaml.safe_load((APP / "envs" / env / "release.yaml").read_text())
                self.assertEqual(set(values), {"image", "env"})
                self.assertEqual(set(values["image"]), {"tag"})
                self.assertEqual(list(values["env"]), ["APP_VERSION", "APP_MESSAGE"])
                message = values["env"]["APP_MESSAGE"]
                self.assertIsNone(re.search(r"['$\\;{}]", message), "message would break the nginx config")

    def test_env_file_names_its_environment(self):
        for env in ENVS:
            with self.subTest(env=env):
                values = yaml.safe_load((APP / "envs" / env / "env.yaml").read_text())
                self.assertEqual(values["environment"], env)


class DemoApplicationTest(unittest.TestCase):
    def test_application_renders_the_base_chart_with_this_environment_values(self):
        for env in ENVS:
            with self.subTest(env=env):
                a = yaml.safe_load((ROOT / f"gitops/clusters/{env}/demo-app.yaml").read_text())
                self.assertEqual(a["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "6")
                chart, ref = a["spec"]["sources"]
                self.assertEqual(chart["path"], "gitops/charts/base-app")
                self.assertEqual(chart["helm"]["releaseName"], "demo-app")
                self.assertEqual(chart["helm"]["valueFiles"], [
                    "$values/gitops/apps/demo-app/values.yaml",
                    f"$values/gitops/apps/demo-app/envs/{env}/env.yaml",
                    f"$values/gitops/apps/demo-app/envs/{env}/release.yaml",
                ])
                self.assertEqual(ref["ref"], "values")
                self.assertEqual(a["spec"]["destination"]["namespace"], "demo")

    def test_namespace_is_created_and_managed_by_the_environment_policy(self):
        for env in ENVS:
            with self.subTest(env=env):
                a = yaml.safe_load((ROOT / f"gitops/clusters/{env}/demo-app.yaml").read_text())
                sync = a["spec"]["syncPolicy"]
                self.assertIn("CreateNamespace=true", sync["syncOptions"])
                self.assertEqual(sync["managedNamespaceMetadata"]["labels"]["k8sdemo.vn/managed"], "true")


if __name__ == "__main__":
    unittest.main()
