"""Shared helpers for repository tests."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANSIBLE = ROOT / "ansible"
ENVS = ("dev", "staging", "prod")


def ansible_env():
    env = dict(os.environ)
    env["ANSIBLE_CONFIG"] = str(ANSIBLE / "ansible.cfg")
    return env


def inventory(env_name):
    """Return `ansible-inventory --list` output for one environment as a dict."""
    out = subprocess.run(
        ["ansible-inventory", "-i", str(ANSIBLE / "inventories" / env_name / "hosts.yml"), "--list"],
        check=True, capture_output=True, text=True, env=ansible_env(),
    ).stdout
    return json.loads(out)


OUT = ROOT / "tests" / "out"
_rendered = set()


def rendered(env_name, name, **extra_vars):
    """Render all role templates for one environment (once per process) and
    return the text of the rendered file `name`."""
    if env_name not in _rendered:
        cmd = ["ansible-playbook", "-i", str(ANSIBLE / "inventories" / env_name / "hosts.yml"),
               str(ROOT / "tests" / "ansible" / "render.yml"),
               "-e", "ansible_connection=local", "-e", "ansible_become=false",
               "-e", "ansible_python_interpreter=" + sys.executable,
               "-e", "kube_vip_interface=eth0",
               "-e", "kube_vip_kubeconfig=/etc/kubernetes/admin.conf"]
        res = subprocess.run(cmd, capture_output=True, text=True, env=ansible_env())
        if res.returncode != 0:
            raise AssertionError("render.yml failed:\n" + res.stdout[-3000:] + res.stderr[-2000:])
        _rendered.add(env_name)
    return (OUT / env_name / name).read_text()


def playbook_listing(flag, playbook="site.yml", env_name="prod"):
    """Return `ansible-playbook --list-tasks/--list-tags` output."""
    return subprocess.run(
        ["ansible-playbook", "-i", str(ANSIBLE / "inventories" / env_name / "hosts.yml"),
         str(ANSIBLE / playbook), flag],
        check=True, capture_output=True, text=True, env=ansible_env(),
    ).stdout


CHART = ROOT / "gitops" / "charts" / "base-app"
APPS = ROOT / "gitops" / "apps"


def helm_template(values_files=(), sets=(), release="app", namespace="apps", check=True):
    """Render gitops/charts/base-app with `helm template`; return the completed process."""
    cmd = ["helm", "template", release, str(CHART), "--namespace", namespace]
    for f in values_files:
        cmd += ["-f", str(f)]
    for s in sets:
        cmd += ["--set", s]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def app_values(app, env):
    """The values files Argo CD passes for one app in one environment, in order."""
    base = APPS / app
    return [base / "values.yaml", base / "envs" / env / "env.yaml", base / "envs" / env / "release.yaml"]
