"""MetalLB and F5 NGINX Ingress: per-environment Applications, pools and ingress IPs."""
import subprocess
import unittest

import yaml

from tests.repo.helpers import ENVS, ROOT

NETS = {"prod": "172.20.0", "staging": "172.20.1", "dev": "172.20.2"}
REPO = "https://github.com/haison8x/k8s-demo.git"


def app(env, name):
    return yaml.safe_load((ROOT / f"gitops/clusters/{env}/{name}.yaml").read_text())


def wave(a):
    return a["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]


def build(path):
    out = subprocess.run(["kubectl", "kustomize", str(ROOT / path)], check=True, capture_output=True, text=True).stdout
    return {(d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(out) if d}


class MetallbTest(unittest.TestCase):
    def test_metallb_application(self):
        for env in ENVS:
            with self.subTest(env=env):
                a = app(env, "metallb")
                src = a["spec"]["source"]
                self.assertEqual((src["repoURL"], src["chart"], src["targetRevision"]),
                                 ("https://metallb.github.io/metallb", "metallb", "0.16.2"))
                self.assertEqual(wave(a), "0")
                self.assertEqual(a["spec"]["destination"]["namespace"], "metallb-system")
                self.assertIn("CreateNamespace=true", a["spec"]["syncPolicy"]["syncOptions"])
                crd_ignores = [i for i in a["spec"]["ignoreDifferences"]
                               if i["group"] == "apiextensions.k8s.io" and i["kind"] == "CustomResourceDefinition"]
                self.assertIn("/spec/conversion/webhook/clientConfig/caBundle", crd_ignores[0]["jsonPointers"])

    def test_metallb_config_application(self):
        for env in ENVS:
            with self.subTest(env=env):
                a = app(env, "metallb-config")
                self.assertEqual(wave(a), "1")
                self.assertEqual(a["spec"]["source"]["path"], f"gitops/platform/metallb/config/overlays/{env}")
                self.assertIn("SkipDryRunOnMissingResource=true", a["spec"]["syncPolicy"]["syncOptions"])
                self.assertGreaterEqual(a["spec"]["syncPolicy"]["retry"]["limit"], 5)

    def test_pool_and_advertisement_per_environment(self):
        for env in ENVS:
            with self.subTest(env=env):
                docs = build(f"gitops/platform/metallb/config/overlays/{env}")
                pool = docs[("IPAddressPool", "demo-pool")]
                net = NETS[env]
                self.assertEqual(pool["spec"]["addresses"], [f"{net}.200-{net}.229"])
                self.assertEqual(pool["metadata"]["namespace"], "metallb-system")
                l2 = docs[("L2Advertisement", "demo-l2")]
                self.assertEqual(l2["spec"]["ipAddressPools"], ["demo-pool"])


class NginxIngressTest(unittest.TestCase):
    def test_application_uses_pinned_chart_and_env_values(self):
        for env in ENVS:
            with self.subTest(env=env):
                a = app(env, "nginx-ingress")
                self.assertEqual(wave(a), "4")
                chart, values = a["spec"]["sources"]
                self.assertEqual((chart["repoURL"], chart["chart"], chart["targetRevision"]),
                                 ("https://helm.nginx.com/stable", "nginx-ingress", "2.8.1"))
                self.assertEqual(chart["helm"]["valueFiles"], [
                    "$values/gitops/platform/nginx-ingress/values.yaml",
                    f"$values/gitops/platform/nginx-ingress/values-{env}.yaml"])
                self.assertEqual((values["repoURL"], values["targetRevision"], values["ref"]), (REPO, "main", "values"))
                self.assertEqual(a["spec"]["destination"]["namespace"], "nginx-ingress")
                self.assertIn("CreateNamespace=true", a["spec"]["syncPolicy"]["syncOptions"])

    def test_common_values(self):
        v = yaml.safe_load((ROOT / "gitops/platform/nginx-ingress/values.yaml").read_text())["controller"]
        self.assertEqual(v["ingressClass"]["name"], "nginx")
        self.assertTrue(v["ingressClass"]["create"])
        self.assertTrue(v["ingressClass"]["setAsDefaultIngress"])
        self.assertEqual(v["service"]["type"], "LoadBalancer")

    def test_environment_load_balancer_ip(self):
        for env in ENVS:
            with self.subTest(env=env):
                v = yaml.safe_load((ROOT / f"gitops/platform/nginx-ingress/values-{env}.yaml").read_text())
                ann = v["controller"]["service"]["annotations"]
                self.assertEqual(ann["metallb.io/loadBalancerIPs"], f"{NETS[env]}.200")


if __name__ == "__main__":
    unittest.main()
