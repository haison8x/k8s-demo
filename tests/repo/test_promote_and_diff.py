"""scripts/promote.sh and env-guard.py check-diff, exercised in throwaway git repositories."""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.repo.helpers import ROOT

RELEASE = "gitops/apps/demo-app/overlays/{}/release.yaml"


def release(version, image="nginx:1.0"):
    """A release.yaml with the same structure as the real ones."""
    return textwrap.dedent(f"""\
        spec:
          template:
            spec:
              containers:
                - name: nginx
                  image: {image}
                  env:
                    - name: APP_VERSION
                      value: "{version}"
        """)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class GitRepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "test")
        for env in ("dev", "staging", "prod"):
            self.write(RELEASE.format(env), release("1.0.0"))
        self.write("README.md", "test\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, newline="\n")

    def commit_on_branch(self, files):
        git(self.repo, "checkout", "-q", "-b", "change")
        for rel, text in files.items():
            self.write(rel, text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "change")


class CheckDiffTest(GitRepoCase):
    def check_diff(self):
        return subprocess.run([sys.executable, str(ROOT / "scripts/env-guard.py"), "check-diff", "main",
                               "--root", str(self.repo)], capture_output=True, text=True)

    def test_change_to_one_environment_passes(self):
        self.commit_on_branch({RELEASE.format("staging"): "image: nginx:2.0\n"})
        res = self.check_diff()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_change_to_two_environments_fails(self):
        self.commit_on_branch({RELEASE.format("dev"): "image: nginx:2.0\n",
                               RELEASE.format("prod"): "image: nginx:2.0\n"})
        res = self.check_diff()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("touches more than one environment: dev, prod", res.stdout)

    def test_shared_change_with_one_environment_passes(self):
        self.commit_on_branch({"README.md": "changed\n", "ansible/inventories/prod/hosts.yml": "x: 1\n"})
        res = self.check_diff()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


class PromoteTest(GitRepoCase):
    def promote(self, path):
        env = dict(os.environ, PROMOTE_LOCAL_ONLY="1")
        return subprocess.run(["bash", str(ROOT / "scripts/promote.sh"), path], cwd=self.repo,
                              capture_output=True, text=True, env=env)

    def test_promotion_copies_the_release_file_on_a_new_branch(self):
        self.write(RELEASE.format("dev"), release("2.0.0", "nginx:2.0"))
        git(self.repo, "commit", "-q", "-am", "dev release 2.0.0")
        res = self.promote("dev-to-staging")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual((self.repo / RELEASE.format("staging")).read_text(),
                         (self.repo / RELEASE.format("dev")).read_text())
        self.assertTrue(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD").startswith("promote/dev-to-staging-"))
        self.assertIn("Promote demo-app dev to staging (2.0.0)", git(self.repo, "log", "-1", "--format=%s"))
        changed = git(self.repo, "show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual(changed, [RELEASE.format("staging")])

    def test_nothing_to_promote_is_not_an_error(self):
        res = self.promote("staging-to-prod")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("nothing to promote", res.stdout)
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD").strip(), "main")

    def test_unknown_promotion_path_fails(self):
        res = self.promote("dev-to-prod")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("usage", res.stderr)


if __name__ == "__main__":
    unittest.main()
