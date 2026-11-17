"""Regression tests for problems found in the whole-branch review."""
import subprocess
import unittest

import yaml

from tests.repo.helpers import ANSIBLE, ENVS, ROOT, ansible_env
from tests.repo.test_task_safety import all_tasks, command_of, creates_of, iter_tasks

ROLES = ANSIBLE / "roles"


def tasks_of(path):
    return yaml.safe_load((ROLES / path).read_text())


def task_text(task):
    return yaml.safe_dump(task)


class CalicoInstallTest(unittest.TestCase):
    def test_crds_are_installed_before_the_operator(self):
        tasks = list(iter_tasks(tasks_of("control_plane/tasks/calico.yml")))
        texts = [task_text(t) for t in tasks]
        crd = next(i for i, t in enumerate(texts) if "manifests/v3_projectcalico_org.yaml" in t)
        operator = next(i for i, t in enumerate(texts) if "manifests/tigera-operator.yaml" in t)
        self.assertLess(crd, operator)

    def test_calico_is_reconciled_on_every_run_not_only_at_init(self):
        main = task_text(tasks_of("control_plane/tasks/main.yml"))
        self.assertIn("calico.yml", main)
        self.assertNotIn("calico", task_text(tasks_of("control_plane/tasks/init.yml")))


class IncompleteKubeadmRunTest(unittest.TestCase):
    """A failed init/join must be retried by re-running, not left half-done."""

    def test_kubeadm_init_and_join_are_guarded_by_completion_markers(self):
        for f, task in all_tasks():
            cmd = command_of(task) or ""
            if ("kubeadm init " in cmd and "phase" not in cmd) or "control_plane_join_command" in cmd:
                self.assertRegex(str(creates_of(task)), r"^/etc/kubernetes/\.k8s-demo-(init|join)-done$",
                                 f"{f}: {task.get('name')}")
                self.assertIn("touch /etc/kubernetes/.k8s-demo-", cmd, f"{f}: {task.get('name')}")

    def test_leftovers_of_an_incomplete_run_are_reset(self):
        for role in ("control_plane", "worker"):
            text = "".join(p.read_text() for p in (ROLES / role / "tasks").glob("*.yml"))
            self.assertIn("Clean up an incomplete kubeadm run", text, role)
            self.assertIn("kubeadm reset -f", text, role)


class PreflightStopsTheRunTest(unittest.TestCase):
    def test_preflight_failure_aborts_every_host(self):
        plays = yaml.safe_load((ANSIBLE / "site.yml").read_text())
        self.assertEqual(plays[0]["roles"], ["preflight"])
        self.assertIs(plays[0].get("any_errors_fatal"), True)


class ArgocdTest(unittest.TestCase):
    def test_child_application_health_gates_the_sync_waves(self):
        for env in ENVS:
            cm = yaml.safe_load((ROOT / f"gitops/platform/argocd/overlays/{env}/argocd-cm.yaml").read_text())
            lua = cm["data"]["resource.customizations.health.argoproj.io_Application"]
            self.assertIn("obj.status.health", lua)

    def test_bcrypt_hashing_works_with_the_pinned_toolchain(self):
        res = subprocess.run(["ansible", "localhost", "-m", "ansible.builtin.debug",
                              "-a", "msg={{ ('a' * 30) | password_hash('bcrypt') }}"],
                             capture_output=True, text=True, env=ansible_env())
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertRegex(res.stdout, r"\$2[aby]\$\d\d\$")

    def test_admin_password_is_set_while_the_initial_secret_exists(self):
        tasks = tasks_of("argocd_bootstrap/tasks/main.yml")
        block = next(t for t in tasks if t.get("name") == "Replace the generated admin password")
        self.assertIn("argocd_bootstrap_initial_secret.rc == 0", block["when"])
        self.assertIn("Set the Argo CD admin password", [t["name"] for t in block["block"]])


class KyvernoSystemConfigMapTest(unittest.TestCase):
    def test_kube_root_ca_is_exempt(self):
        pol = (ROOT / "gitops/platform/kyverno/policies/require-matching-env.yaml").read_text()
        self.assertIn("kube-root-ca.crt", pol)
        test = yaml.safe_load((ROOT / "tests/kyverno/kyverno-test.yaml").read_text())
        self.assertIn("resources/kube-root-ca.yaml", test["resources"])


class ResetTest(unittest.TestCase):
    def test_reset_opens_default_policies_before_flushing(self):
        text = (ANSIBLE / "reset.yml").read_text()
        self.assertIn("iptables -P INPUT ACCEPT", text)
        self.assertLess(text.index("iptables -P INPUT ACCEPT"), text.index('-F;'))


class GithubSetupTest(unittest.TestCase):
    def dry_run(self):
        return subprocess.run(["bash", str(ROOT / "scripts/github-setup.sh"), "--dry-run"],
                              capture_output=True, text=True, check=True).stdout

    def test_colleague_gets_write_access(self):
        out = self.dry_run()
        self.assertIn("repos/haison8x/k8s-demo/collaborators/haison9x", out)
        self.assertIn('"permission":"push"', out)

    def test_dev_pull_requests_do_not_need_an_approval(self):
        self.assertIn('"require_last_push_approval":false', self.dry_run())


class CodeownersTest(unittest.TestCase):
    def test_ansible_config_is_owned(self):
        self.assertIn("/ansible/ansible.cfg @haison8x @haison9x",
                      (ROOT / ".github/CODEOWNERS").read_text())


if __name__ == "__main__":
    unittest.main()
