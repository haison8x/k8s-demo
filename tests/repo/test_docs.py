"""README and the GitHub Pages guide: self-contained, consistent with the environment plan."""
import re
import subprocess
import unittest
from html.parser import HTMLParser

from tests.repo.helpers import ROOT

FACTS = [
    "k8sdemo.vn", "staging.k8sdemo.vn", "dev.k8sdemo.vn",
    "argocd.k8sdemo.vn", "argocd.staging.k8sdemo.vn", "argocd.dev.k8sdemo.vn",
    "172.20.0.100", "172.20.1.100", "172.20.2.100",
    "172.20.0.200", "172.20.1.200", "172.20.2.200",
    "172.20.0.0/24", "172.20.1.0/24", "172.20.2.0/24", "172.20.9.5",
    "10.244.0.0/16", "proxy.mycompany.com:3128",
    "scripts/github-setup.sh", "scripts/get-kubeconfig.sh", "scripts/install-tools.sh",
    "ansible/ops.yml", "release.yaml", "env.yaml",
]
SECTIONS = ["overview", "status", "concepts", "architecture", "environments", "layout", "switch", "before",
            "setup", "verify", "operations", "promotion", "new-app", "secrets", "guard-rails", "contributing", "manual",
            "demo", "troubleshooting", "limitations"]
# Onboarding topics both documents must cover.
TOPICS = ["AUTOMATION_ENABLED", "k8s-demo-promoter", "ssh-keygen", "ARGOCD_ADMIN_PASSWORD", "SSH_PRIVATE_KEY",
          "PROMOTER_PRIVATE_KEY", "registry.k8s.io", "--dry-run", "confirm_reset", "docs/VERSIONS.md",
          "gitops/charts/base-app", "gitops/apps/demo-app/envs/dev/release.yaml", "Add a new app with the base chart"]
# Paths of the old Kustomize layout of the demo app must not come back.
STALE = ["demo-app/overlays", "demo-app/base", "apps/demo-app/{base,overlays"]
# Assembled from pieces so this file does not match its own check.
FORBIDDEN = re.compile("|".join(["Clau" + "de", "Anthro" + "pic", "super" + "powers", "agen" + "tic",
                                 "Co-Auth" + "ored-By"]), re.IGNORECASE)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.external, self.title = set(), [], ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "script" and a.get("src"):
            self.external.append(a["src"])
        if tag == "link" and a.get("href", "").startswith(("http:", "https:", "//")):
            self.external.append(a["href"])
        if tag == "img" and a.get("src", "").startswith(("http:", "https:", "//")):
            self.external.append(a["src"])
        self._in_title = tag == "title"

    def handle_data(self, data):
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag):
        self._in_title = False


class PagesGuideTest(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.page = PageParser()
        self.page.feed(self.html)

    def test_page_is_self_contained(self):
        self.assertEqual(self.page.external, [])
        self.assertTrue((ROOT / ".nojekyll").exists())

    def test_page_structure(self):
        self.assertTrue(self.page.title.strip())
        for section in SECTIONS:
            self.assertIn(section, self.page.ids)
        self.assertIn('name="viewport"', self.html)
        self.assertIn("prefers-color-scheme: dark", self.html)

    def test_page_states_the_plan(self):
        for fact in FACTS + TOPICS:
            self.assertIn(fact, self.html)

    def test_no_stale_paths(self):
        for stale in STALE:
            self.assertNotIn(stale.replace("<", "&lt;").replace(">", "&gt;"), self.html)

    def test_navigation_links_every_section(self):
        for section in SECTIONS:
            self.assertIn(f'href="#{section}"', self.html)


class ReadmeTest(unittest.TestCase):
    def test_readme_states_the_plan_and_links_the_guide(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://haison8x.github.io/k8s-demo/", text)
        for fact in FACTS + TOPICS:
            self.assertIn(fact, text)
        for stale in STALE:
            self.assertNotIn(stale, text)


class NoToolMentionsTest(unittest.TestCase):
    def test_tracked_files_and_history_are_clean(self):
        files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
                               check=True, capture_output=True, text=True).stdout.split()
        for rel in files:
            path = ROOT / rel
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertIsNone(FORBIDDEN.search(text), rel)
        log = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%an%n%ae%n%B"],
                             check=True, capture_output=True, text=True).stdout
        self.assertIsNone(FORBIDDEN.search(log), "commit history")


if __name__ == "__main__":
    unittest.main()
