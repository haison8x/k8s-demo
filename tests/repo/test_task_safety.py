"""Static safety rules for every Ansible task in the roles and playbooks."""
import unittest

import yaml

from tests.repo.helpers import ANSIBLE

SECRET_VARS = ("control_plane_join_command", "control_plane_certificate_key", "argocd_bootstrap_admin_password",
               "runner_registration_token")
CMD_MODULES = ("ansible.builtin.command", "ansible.builtin.shell")


def iter_tasks(node):
    """Yield every task dict, descending into block/rescue/always."""
    if isinstance(node, list):
        for item in node:
            yield from iter_tasks(item)
    elif isinstance(node, dict):
        if any(k in node for k in ("block", "rescue", "always")):
            for k in ("block", "rescue", "always"):
                yield from iter_tasks(node.get(k, []))
        else:
            yield node


def all_tasks():
    files = list((ANSIBLE / "roles").glob("*/tasks/*.yml")) + list((ANSIBLE / "roles").glob("*/handlers/*.yml"))
    for f in files:
        for task in iter_tasks(yaml.safe_load(f.read_text()) or []):
            yield f, task


def command_of(task):
    for m in CMD_MODULES:
        if m in task:
            v = task[m]
            return v if isinstance(v, str) else (v or {}).get("cmd", "")
    return None


def creates_of(task):
    for m in CMD_MODULES:
        if isinstance(task.get(m), dict) and task[m].get("creates"):
            return task[m]["creates"]
    return (task.get("args") or {}).get("creates")


class TaskSafetyTest(unittest.TestCase):
    def test_kubeadm_init_and_join_are_guarded_by_creates(self):
        found = []
        for f, task in all_tasks():
            cmd = command_of(task)
            if cmd and ("kubeadm init " in cmd and "phase" not in cmd or "kubeadm join" in cmd
                        or "control_plane_join_command" in cmd):
                found.append(task.get("name"))
                self.assertTrue(creates_of(task), f"{f.name}: '{task.get('name')}' has no creates:")
        self.assertGreaterEqual(len(found), 3, f"expected kubeadm init/join tasks, found {found}")

    def test_tasks_copying_kubeconfigs_never_print_a_diff(self):
        """Drift runs use --diff and workflow logs are public; admin.conf holds a private key."""
        found = 0
        for f, task in all_tasks():
            body = yaml.safe_dump({k: v for k, v in task.items() if k != "name"})
            if "admin.conf" in body and any(m in task for m in ("ansible.builtin.copy", "ansible.builtin.fetch")):
                found += 1
                self.assertIs(task.get("diff"), False, f"{f}: '{task.get('name')}' must set diff: false")
        self.assertGreaterEqual(found, 1)

    def test_tasks_touching_secrets_do_not_log(self):
        for f, task in all_tasks():
            body = {k: v for k, v in task.items() if k not in ("when", "name")}
            if any(s in yaml.safe_dump(body) for s in SECRET_VARS):
                self.assertTrue(task.get("no_log"), f"{f}: '{task.get('name')}' uses a secret without no_log")


if __name__ == "__main__":
    unittest.main()
