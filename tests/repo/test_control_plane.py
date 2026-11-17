"""kube-vip, kubeadm and Calico configuration rendered for each environment."""
import unittest

import yaml

from tests.repo.helpers import ENVS, rendered

NETS = {"prod": "172.20.0", "staging": "172.20.1", "dev": "172.20.2"}
CPS = {"prod": [5, 6, 7], "staging": [5, 6, 7], "dev": [5]}


def docs(text):
    return {d["kind"]: d for d in yaml.safe_load_all(text) if d}


class KubeVipTest(unittest.TestCase):
    def test_static_pod_advertises_the_environment_vip(self):
        for env in ENVS:
            with self.subTest(env=env):
                pod = yaml.safe_load(rendered(env, "kube-vip.yaml"))
                c = pod["spec"]["containers"][0]
                envs = {e["name"]: e["value"] for e in c["env"]}
                self.assertEqual(envs["address"], f"{NETS[env]}.100")
                self.assertEqual(envs["vip_arp"], "true")
                self.assertEqual(envs["cp_enable"], "true")
                self.assertEqual(envs["svc_enable"], "false")
                self.assertEqual(envs["port"], "6443")
                self.assertEqual(envs["vip_interface"], "eth0")
                self.assertEqual(c["image"], "ghcr.io/kube-vip/kube-vip:v1.3.1")
                self.assertTrue(pod["spec"]["hostNetwork"])
                paths = [v["hostPath"]["path"] for v in pod["spec"]["volumes"]]
                self.assertEqual(paths, ["/etc/kubernetes/admin.conf"])


class KubeadmConfigTest(unittest.TestCase):
    def test_cluster_configuration(self):
        for env in ENVS:
            with self.subTest(env=env):
                d = docs(rendered(env, "kubeadm-init.yaml"))
                net = NETS[env]
                cc = d["ClusterConfiguration"]
                self.assertEqual(cc["controlPlaneEndpoint"], f"{net}.100:6443")
                self.assertEqual(cc["networking"]["podSubnet"], "10.244.0.0/16")
                self.assertEqual(cc["networking"]["serviceSubnet"], "10.96.0.0/12")
                self.assertEqual(cc["clusterName"], f"k8s-demo-{env}")
                sans = cc["apiServer"]["certSANs"]
                self.assertIn(f"{net}.100", sans)
                for octet in CPS[env]:
                    self.assertIn(f"{net}.{octet}", sans)
                self.assertEqual(d["InitConfiguration"]["localAPIEndpoint"]["advertiseAddress"], f"{net}.5")
                self.assertEqual(d["KubeletConfiguration"]["cgroupDriver"], "systemd")

    def test_calico_uses_the_pod_cidr(self):
        d = docs(rendered("prod", "calico-installation.yaml"))
        pool = d["Installation"]["spec"]["calicoNetwork"]["ipPools"][0]
        self.assertEqual(pool["cidr"], "10.244.0.0/16")
        self.assertEqual(pool["encapsulation"], "VXLANCrossSubnet")
        self.assertIn("APIServer", d)


class ReservedAddressesTest(unittest.TestCase):
    def test_free_ip_check_covers_vip_and_whole_pool(self):
        for env in ENVS:
            with self.subTest(env=env):
                ips = rendered(env, "reserved-ips").split()
                net = NETS[env]
                self.assertEqual(ips[0], f"{net}.100")
                self.assertEqual(ips[1:], [f"{net}.{i}" for i in range(200, 230)])


if __name__ == "__main__":
    unittest.main()
