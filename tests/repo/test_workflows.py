"""GitHub Actions workflows and CODEOWNERS: safety rules for a public repository."""
import re
import unittest

import yaml

from tests.repo.helpers import ROOT

WF = ROOT / ".github/workflows"
OWNERS = "@haison8x @haison9x"


def workflow(name):
    data = yaml.safe_load((WF / name).read_text())
    # PyYAML reads the bare key `on` as boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def all_workflows():
    return {p.name: workflow(p.name) for p in sorted(WF.glob("*.yml"))}


def runs_on(job):
    r = job.get("runs-on", [])
    return r if isinstance(r, list) else [r]


class WorkflowSafetyTest(unittest.TestCase):
    def test_expected_workflows_exist(self):
        self.assertEqual(set(all_workflows()), {"validate.yml", "ansible.yml", "drift.yml", "promote.yml"})

    def test_pull_request_workflows_never_use_the_self_hosted_runner(self):
        for name, wf in all_workflows().items():
            if {"pull_request", "pull_request_target"} & set(wf["on"] or {}):
                for job_name, job in wf["jobs"].items():
                    self.assertNotIn("self-hosted", runs_on(job), f"{name}:{job_name}")

    def test_self_hosted_jobs_run_only_from_main_with_an_environment(self):
        for name, wf in all_workflows().items():
            for job_name, job in wf["jobs"].items():
                if "self-hosted" in runs_on(job):
                    self.assertEqual(set(wf["on"]) - {"workflow_dispatch", "schedule"}, set(), name)
                    self.assertIn("refs/heads/main", job.get("if", ""), f"{name}:{job_name}")
                    self.assertIn("environment", job, f"{name}:{job_name}")

    def test_every_job_is_off_until_automation_is_enabled(self):
        """Nothing runs after a push until the AUTOMATION_ENABLED repository variable is 'true'."""
        for name, wf in all_workflows().items():
            for job_name, job in wf["jobs"].items():
                self.assertIn("vars.AUTOMATION_ENABLED == 'true'", job.get("if", ""), f"{name}:{job_name}")

    def test_the_automation_switch_is_documented(self):
        for doc in ("README.md", "index.html"):
            self.assertIn("AUTOMATION_ENABLED", (ROOT / doc).read_text(encoding="utf-8"), doc)

    def test_every_action_is_pinned_to_a_commit(self):
        for name, wf in all_workflows().items():
            for job in wf["jobs"].values():
                for step in job.get("steps", []):
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$", f"{name}: {step['uses']}")

    def test_workflows_default_to_read_only_token(self):
        for name, wf in all_workflows().items():
            self.assertEqual(wf.get("permissions"), {"contents": "read"}, name)

    def test_inputs_are_not_interpolated_into_scripts(self):
        """Inputs reach scripts only through env: (prevents script injection)."""
        for name, wf in all_workflows().items():
            for job in wf["jobs"].values():
                for step in job.get("steps", []):
                    self.assertNotRegex(step.get("run", ""), r"\$\{\{\s*(inputs|github\.event|matrix)\.",
                                        f"{name}: {step.get('name')}")


class WorkflowBehaviourTest(unittest.TestCase):
    def test_validate_runs_the_repository_checks_and_the_diff_guard(self):
        wf = workflow("validate.yml")
        self.assertIn("pull_request", wf["on"])
        steps = yaml.safe_dump(wf["jobs"]["validate"]["steps"])
        self.assertIn("bash scripts/validate.sh", steps)
        self.assertIn("env-guard.py check-diff", steps)

    def test_ansible_workflow_inputs_and_environment(self):
        wf = workflow("ansible.yml")
        inputs = wf["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["env"]["options"], ["dev", "staging", "prod"])
        self.assertEqual(inputs["playbook"]["options"], ["site", "reset"])
        self.assertIn("confirm", inputs)
        job = wf["jobs"]["run"]
        self.assertEqual(job["environment"], "${{ inputs.env }}")
        self.assertIn("k8s-demo-ops", runs_on(job))
        text = (WF / "ansible.yml").read_text()
        self.assertIn("secrets.SSH_PRIVATE_KEY", text)
        self.assertIn("secrets.ARGOCD_ADMIN_PASSWORD", text)
        self.assertRegex(text, r"if: always\(\)")

    def test_drift_workflow_checks_every_environment_in_check_mode(self):
        wf = workflow("drift.yml")
        self.assertIn("schedule", wf["on"])
        job = wf["jobs"]["drift"]
        self.assertEqual(job["strategy"]["matrix"]["env"], ["dev", "staging", "prod"])
        self.assertEqual(job["environment"], "${{ matrix.env }}-drift")
        text = (WF / "drift.yml").read_text()
        self.assertIn("--check --diff --tags drift", text)
        self.assertIn("changed=[1-9]", text)

    def test_promote_opens_the_pull_request_as_the_github_app(self):
        wf = workflow("promote.yml")
        self.assertEqual(wf["on"]["workflow_dispatch"]["inputs"]["path"]["options"],
                         ["dev-to-staging", "staging-to-prod"])
        steps = wf["jobs"]["promote"]["steps"]
        token_step = next(s for s in steps if "create-github-app-token" in s.get("uses", ""))
        self.assertEqual(token_step["with"]["client-id"], "${{ secrets.PROMOTER_CLIENT_ID }}")
        promote = next(s for s in steps if "promote.sh" in s.get("run", ""))
        self.assertEqual(promote["env"]["GH_TOKEN"], f"${{{{ steps.{token_step['id']}.outputs.token }}}}")

    def test_promote_takes_the_app_name(self):
        wf = workflow("promote.yml")
        app = wf["on"]["workflow_dispatch"]["inputs"]["app"]
        self.assertEqual(app["default"], "demo-app")
        promote = next(s for s in wf["jobs"]["promote"]["steps"] if "promote.sh" in s.get("run", ""))
        self.assertEqual(promote["env"]["APP"], "${{ inputs.app }}")
        self.assertIn('"$APP"', promote["run"])


class CodeownersTest(unittest.TestCase):
    REQUIRED = [
        "/gitops/apps/*/envs/prod/", "/gitops/apps/*/envs/staging/", "/gitops/apps/*/values.yaml",
        "/gitops/charts/",
        "/gitops/clusters/prod/", "/gitops/clusters/staging/",
        "/ansible/inventories/prod/", "/ansible/inventories/staging/",
        "/gitops/platform/", "/ansible/roles/", "/ansible/*.yml",
        "/ansible/group_vars/", "/.github/", "/scripts/",
    ]

    def test_shared_staging_and_prod_paths_are_owned(self):
        rules = {}
        for line in (ROOT / ".github/CODEOWNERS").read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                path, owners = line.split(None, 1)
                rules[path] = owners.strip()
        for path in self.REQUIRED:
            self.assertEqual(rules.get(path), OWNERS, path)
        self.assertNotIn("*", rules)
        self.assertFalse([p for p in rules if re.search(r"/dev/", p)], "dev paths must stay unowned")


if __name__ == "__main__":
    unittest.main()
