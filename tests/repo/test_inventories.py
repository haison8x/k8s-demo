"""Inventories: exact hosts, addresses and per-environment variables."""
import unittest

from tests.repo.helpers import inventory

EXPECTED = {
    "prod": {
        "subnet": "172.20.0",
        "control_plane": {"prod-cp1": 5, "prod-cp2": 6, "prod-cp3": 7},
        "workers": {"prod-worker1": 8, "prod-worker2": 9, "prod-worker3": 10},
        "app_host": "k8sdemo.vn",
        "argocd_host": "argocd.k8sdemo.vn",
    },
    "staging": {
        "subnet": "172.20.1",
        "control_plane": {"stg-cp1": 5, "stg-cp2": 6, "stg-cp3": 7},
        "workers": {"stg-worker1": 8, "stg-worker2": 9},
        "app_host": "staging.k8sdemo.vn",
        "argocd_host": "argocd.staging.k8sdemo.vn",
    },
    "dev": {
        "subnet": "172.20.2",
        "control_plane": {"dev-cp1": 5},
        "workers": {"dev-worker1": 6},
        "app_host": "dev.k8sdemo.vn",
        "argocd_host": "argocd.dev.k8sdemo.vn",
    },
}

PROXY = "http://proxy.mycompany.com:3128"


class InventoryTest(unittest.TestCase):
    def test_hosts_and_addresses(self):
        for env, exp in EXPECTED.items():
            with self.subTest(env=env):
                inv = inventory(env)
                hostvars = inv["_meta"]["hostvars"]
                for group in ("control_plane", "workers"):
                    self.assertEqual(sorted(inv[group]["hosts"]), sorted(exp[group]))
                    for host, octet in exp[group].items():
                        self.assertEqual(hostvars[host]["ansible_host"], f"{exp['subnet']}.{octet}")
                self.assertEqual(sorted(inv["k8s_cluster"]["children"]), ["control_plane", "workers"])

    def test_environment_variables(self):
        for env, exp in EXPECTED.items():
            with self.subTest(env=env):
                inv = inventory(env)
                any_host = next(iter(exp["control_plane"]))
                v = inv["_meta"]["hostvars"][any_host]
                net = exp["subnet"]
                self.assertEqual(v["env"], env)
                self.assertEqual(v["env_subnet"], f"{net}.0/24")
                self.assertEqual(v["kube_vip_address"], f"{net}.100")
                self.assertEqual(v["metallb_range_start"], f"{net}.200")
                self.assertEqual(v["metallb_range_end"], f"{net}.229")
                self.assertEqual(v["ingress_ip"], f"{net}.200")
                self.assertEqual(v["proxy_http"], PROXY)
                self.assertEqual(v["proxy_https"], PROXY)
                self.assertEqual(v["argocd_root_path"], f"gitops/clusters/{env}")
                self.assertEqual(v["app_host"], exp["app_host"])
                self.assertEqual(v["argocd_host"], exp["argocd_host"])
                no_proxy = v["proxy_no_proxy"].split(",")
                for entry in ("localhost", "127.0.0.1", f"{net}.0/24", f"{net}.100",
                              "10.244.0.0/16", "10.96.0.0/12", ".svc", ".cluster.local", ".k8sdemo.vn"):
                    self.assertIn(entry, no_proxy)

    def test_ops_inventory(self):
        inv = inventory("ops")
        self.assertEqual(inv["ops"]["hosts"], ["ops1"])
        self.assertEqual(inv["_meta"]["hostvars"]["ops1"]["ansible_host"], "172.20.9.5")


if __name__ == "__main__":
    unittest.main()
