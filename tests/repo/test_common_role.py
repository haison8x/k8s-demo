"""Role `common`: proxy configuration and the tasks other tooling relies on."""
import unittest

from tests.repo.helpers import ENVS, playbook_listing, rendered

PROXY = "http://proxy.mycompany.com:3128"
SUBNETS = {"prod": "172.20.0", "staging": "172.20.1", "dev": "172.20.2"}


def required_no_proxy(env):
    net = SUBNETS[env]
    return ["localhost", "127.0.0.1", f"{net}.0/24", f"{net}.100",
            "10.244.0.0/16", "10.96.0.0/12", ".svc", ".cluster.local"]


class ProxyTemplatesTest(unittest.TestCase):
    def test_environment_file_has_proxy_and_full_no_proxy(self):
        for env in ENVS:
            with self.subTest(env=env):
                text = rendered(env, "environment")
                self.assertIn(f"HTTPS_PROXY={PROXY}", text)
                self.assertIn(f"https_proxy={PROXY}", text)
                no_proxy = next(l for l in text.splitlines() if l.startswith("no_proxy=")).split("=", 1)[1]
                for entry in required_no_proxy(env):
                    self.assertIn(entry, no_proxy.split(","))
                self.assertIn("NO_PROXY=" + no_proxy, text)

    def test_containerd_dropin_has_no_proxy_for_cluster_ranges(self):
        for env in ENVS:
            with self.subTest(env=env):
                text = rendered(env, "containerd-proxy.conf")
                self.assertIn("[Service]", text)
                self.assertIn(f'Environment="HTTPS_PROXY={PROXY}"', text)
                line = next(l for l in text.splitlines() if l.startswith('Environment="NO_PROXY='))
                for entry in required_no_proxy(env):
                    self.assertIn(entry, line)

    def test_apt_proxy(self):
        text = rendered("prod", "apt-proxy.conf")
        self.assertIn(f'Acquire::http::Proxy "{PROXY}";', text)
        self.assertIn(f'Acquire::https::Proxy "{PROXY}";', text)


class CommonTasksTest(unittest.TestCase):
    def test_named_tasks_present(self):
        tasks = playbook_listing("--list-tasks")
        for name in ("common : Disable swap", "common : Configure containerd SystemdCgroup",
                     "common : Hold kubernetes packages"):
            self.assertIn(name, tasks)

    def test_drift_tag_exists(self):
        self.assertIn("drift", playbook_listing("--list-tags"))


if __name__ == "__main__":
    unittest.main()
