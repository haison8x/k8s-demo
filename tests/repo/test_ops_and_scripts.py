"""Ops runner configuration and the one-time helper scripts."""
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import jinja2
import yaml

from tests.repo.helpers import ANSIBLE, ROOT, ansible_env

PROXY = "http://proxy.mycompany.com:3128"


class OpsRunnerTest(unittest.TestCase):
    def test_ops_playbook_syntax(self):
        res = subprocess.run(["ansible-playbook", "-i", str(ANSIBLE / "inventories/ops/hosts.yml"),
                              "--syntax-check", str(ANSIBLE / "ops.yml")],
                             capture_output=True, text=True, env=ansible_env())
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_ops_variables(self):
        v = yaml.safe_load((ANSIBLE / "inventories/ops/group_vars/all.yml").read_text())
        self.assertEqual(v["proxy_http"], PROXY)
        self.assertEqual(v["proxy_https"], PROXY)
        for entry in ("localhost", "127.0.0.1", "172.20.0.0/16"):
            self.assertIn(entry, v["proxy_no_proxy"].split(","))
        self.assertEqual(v["ops_runner_version"], "2.338.2")
        self.assertEqual(v["ops_runner_labels"], "k8s-demo-ops")
        self.assertEqual(v["ops_runner_repo_url"], "https://github.com/haison8x/k8s-demo")

    def test_runner_environment_file(self):
        v = yaml.safe_load((ANSIBLE / "inventories/ops/group_vars/all.yml").read_text())
        src = (ANSIBLE / "roles/ops_runner/templates/runner.env.j2").read_text()
        text = jinja2.Template(src).render(**v)
        self.assertIn(f"https_proxy={PROXY}", text)
        self.assertIn(f"HTTPS_PROXY={PROXY}", text)
        self.assertIn("no_proxy=" + v["proxy_no_proxy"], text)


class GithubSetupTest(unittest.TestCase):
    def test_dry_run_shows_every_setting(self):
        res = subprocess.run(["bash", str(ROOT / "scripts/github-setup.sh"), "--dry-run"],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        out = res.stdout
        for needle in ('"required_approving_review_count":0', '"require_code_owner_review":true',
                       '"context":"validate"', "repos/haison8x/k8s-demo/rulesets",
                       "environments/dev ", "environments/staging ", "environments/prod ",
                       "environments/dev-drift ", "environments/staging-drift ", "environments/prod-drift ",
                       "SSH_PRIVATE_KEY", "ARGOCD_ADMIN_PASSWORD", "PROMOTER_CLIENT_ID", "PROMOTER_PRIVATE_KEY",
                       "repos/haison8x/k8s-demo/pages", '"default_workflow_permissions":"read"'):
            self.assertIn(needle, out)
        prod_line = next(l for l in out.splitlines() if "environments/prod " in l)
        self.assertIn("haison8x", prod_line)
        self.assertIn("haison9x", prod_line)
        dev_line = next(l for l in out.splitlines() if "environments/dev " in l)
        self.assertIn('"reviewers":[]', dev_line)


def sample_kubeconfig(server, context="kubernetes-admin@k8s-demo-prod"):
    return textwrap.dedent(f"""\
        apiVersion: v1
        kind: Config
        clusters:
          - name: k8s-demo-prod
            cluster:
              server: {server}
        contexts:
          - name: {context}
            context:
              cluster: k8s-demo-prod
              user: kubernetes-admin
        current-context: {context}
        users:
          - name: kubernetes-admin
            user:
              token: test
        """)


class GetKubeconfigTest(unittest.TestCase):
    def run_script(self, env_name, server):
        tmp = tempfile.mkdtemp()
        src = Path(tmp) / "admin.conf"
        src.write_text(sample_kubeconfig(server))
        env = dict(os.environ, KUBECONFIG_SOURCE=str(src), KUBECONFIG_DIR=str(Path(tmp) / "kube"))
        res = subprocess.run(["bash", str(ROOT / "scripts/get-kubeconfig.sh"), env_name],
                             capture_output=True, text=True, env=env)
        return res, Path(tmp) / "kube" / f"k8s-demo-{env_name}.kubeconfig"

    def test_saves_a_separate_kubeconfig_with_an_environment_context(self):
        res, out = self.run_script("prod", "https://172.20.0.100:6443")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("haison@172.20.0.5", res.stdout)
        self.assertIn(f"export KUBECONFIG={out}", res.stdout)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
        cfg = yaml.safe_load(out.read_text())
        self.assertEqual(cfg["current-context"], "k8s-demo-prod")

    def test_refuses_a_kubeconfig_for_another_api_server(self):
        res, out = self.run_script("prod", "https://172.20.1.100:6443")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("expected https://172.20.0.100:6443", res.stderr)
        self.assertFalse(out.exists())

    def test_unknown_environment(self):
        res = subprocess.run(["bash", str(ROOT / "scripts/get-kubeconfig.sh"), "qa"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("usage", res.stderr)


if __name__ == "__main__":
    unittest.main()
