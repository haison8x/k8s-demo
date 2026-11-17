"""Shared helpers for repository tests."""
import json
import os
import subprocess
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
