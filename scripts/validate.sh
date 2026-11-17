#!/usr/bin/env bash
# Repository validation: the single test command, used locally and in CI.
# Every check is offline except kubeconform schema downloads and remote
# kustomize bases. Exits non-zero on the first failing check.
set -euo pipefail

cd "$(dirname "$0")/.."
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
ENVS=(dev staging prod)

step() { printf '\n==> %s\n' "$*"; }

step "yamllint"
yamllint -s .

step "actionlint"
actionlint

step "shellcheck"
shellcheck scripts/*.sh tests/ansible/*.sh
echo "ok"

step "ansible syntax-check"
for env in "${ENVS[@]}"; do
  for pb in ansible/site.yml ansible/reset.yml; do
    ansible-playbook -i "ansible/inventories/$env/hosts.yml" --syntax-check "$pb" >/dev/null
  done
done
echo "ok"

step "ansible-lint"
ansible-lint -q ansible/

step "pre-flight guard"
bash tests/ansible/preflight.sh

step "reset guard"
bash tests/ansible/reset.sh

step "helm lint: base chart with every app and environment"
for app_dir in gitops/apps/*/; do
  app=$(basename "$app_dir")
  for env in "${ENVS[@]}"; do
    helm lint --strict --quiet gitops/charts/base-app --namespace "$app" \
      -f "$app_dir/values.yaml" -f "$app_dir/envs/$env/env.yaml" -f "$app_dir/envs/$env/release.yaml" >/dev/null
  done
done
echo "ok"

step "kyverno policy tests"
kyverno test tests/kyverno

step "demo page smoke test"
bash scripts/smoke-demo-page.sh

step "environment guard"
python scripts/env-guard.py check-tree

step "repository tests"
python -m unittest discover -s tests/repo -t . 2>&1 | tail -n 40

echo
echo "All checks passed."
