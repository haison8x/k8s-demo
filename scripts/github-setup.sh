#!/usr/bin/env bash
# One-time (idempotent) GitHub setup for the repository: branch ruleset,
# environments and their secrets, read-only workflow token, fork pull request
# approval and GitHub Pages. Requires `gh auth login` as a repository admin.
#
#   scripts/github-setup.sh [--dry-run] [--promoter-client-id ID] [--promoter-key-file PEM]
#
# SSH keys are read from ~/.ssh/k8s-demo/<env>. Argo CD admin passwords are
# generated once per environment and printed to this terminal only.
set -euo pipefail

REPO=haison8x/k8s-demo
REVIEWERS=(haison8x haison9x)
ENVS=(dev staging prod)
KEY_DIR="${KEY_DIR:-$HOME/.ssh/k8s-demo}"
DRY_RUN=0
PROMOTER_CLIENT_ID=""
PROMOTER_KEY_FILE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --promoter-client-id) PROMOTER_CLIENT_ID=$2; shift ;;
    --promoter-key-file) PROMOTER_KEY_FILE=$2; shift ;;
    *) echo "usage: $0 [--dry-run] [--promoter-client-id ID] [--promoter-key-file PEM]" >&2; exit 2 ;;
  esac
  shift
done

# api METHOD PATH [JSON]: call the GitHub API, or print the call in dry-run mode.
api() {
  local method=$1 path=$2 body=${3:-}
  if [ "$DRY_RUN" = 1 ]; then
    echo "gh api -X $method $path ${body}"
    return 0
  fi
  if [ -n "$body" ]; then
    gh api -X "$method" "$path" --input - <<<"$body" >/dev/null
  else
    gh api -X "$method" "$path" >/dev/null
  fi
}

# secret NAME ENV|- SOURCE_DESCRIPTION: value on stdin.
secret() {
  local name=$1 env=$2 what=$3
  if [ "$DRY_RUN" = 1 ]; then
    cat >/dev/null
    if [ "$env" = "-" ]; then
      echo "gh secret set $name (repository secret) from $what"
    else
      echo "gh secret set $name --env $env from $what"
    fi
    return 0
  fi
  if [ "$env" = "-" ]; then
    gh secret set "$name" --repo "$REPO"
  else
    gh secret set "$name" --repo "$REPO" --env "$env"
  fi
}

user_id() {
  if [ "$DRY_RUN" = 1 ]; then echo "\"<id of $1>\""; else gh api "users/$1" --jq .id; fi
}

if [ "$DRY_RUN" = 0 ]; then
  gh auth status >/dev/null
fi

echo "== Workflow token: read-only by default"
api PUT "repos/$REPO/actions/permissions/workflow" \
  '{"default_workflow_permissions":"read","can_approve_pull_request_reviews":false}'

echo "== Fork pull requests: approval required for all outside contributors"
if ! api PUT "repos/$REPO/actions/permissions/fork-pr-contributor-approval" \
    '{"approval_policy":"all_external_contributors"}'; then
  echo "   Could not set it through the API. Set it by hand: Settings > Actions > General >"
  echo "   'Approval for running fork pull request workflows' > 'Require approval for all external contributors'."
fi

echo "== Ruleset on main: pull request + green 'validate' + code owner review"
ruleset='{"name":"main-protection","target":"branch","enforcement":"active",
"conditions":{"ref_name":{"include":["~DEFAULT_BRANCH"],"exclude":[]}},
"rules":[{"type":"deletion"},{"type":"non_fast_forward"},
{"type":"pull_request","parameters":{"required_approving_review_count":0,"require_code_owner_review":true,
"dismiss_stale_reviews_on_push":true,"require_last_push_approval":true,"required_review_thread_resolution":false}},
{"type":"required_status_checks","parameters":{"strict_required_status_checks_policy":false,
"required_status_checks":[{"context":"validate"}]}}]}'
ruleset=$(tr -d '\n' <<<"$ruleset")
existing=""
if [ "$DRY_RUN" = 0 ]; then
  existing=$(gh api "repos/$REPO/rulesets" --jq '.[] | select(.name=="main-protection") | .id')
fi
if [ -n "$existing" ]; then
  api PUT "repos/$REPO/rulesets/$existing" "$ruleset"
else
  api POST "repos/$REPO/rulesets" "$ruleset"
fi

echo "== Environments"
reviewers_json=""
for r in "${REVIEWERS[@]}"; do
  reviewers_json+="${reviewers_json:+,}{\"type\":\"User\",\"id\":$(user_id "$r")}"
done
branch_policy='"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}'

for env in "${ENVS[@]}"; do
  for name in "$env" "$env-drift"; do
    reviewers="[]"
    if [ "$name" = prod ]; then reviewers="[$reviewers_json]"; fi
    api PUT "repos/$REPO/environments/$name" "{\"reviewers\":$reviewers,\"prevent_self_review\":false,$branch_policy}"
    # Fails harmlessly when the policy already exists.
    api POST "repos/$REPO/environments/$name/deployment-branch-policies" '{"name":"main","type":"branch"}' 2>/dev/null || true

    key="$KEY_DIR/$env"
    if [ "$DRY_RUN" = 1 ]; then
      secret SSH_PRIVATE_KEY "$name" "the $env key file" </dev/null
    elif [ -f "$key" ]; then
      secret SSH_PRIVATE_KEY "$name" "the $env key file" < "$key"
    else
      echo "   missing $key: SSH_PRIVATE_KEY for $name not set"
    fi
  done

  if [ "$DRY_RUN" = 1 ]; then
    secret ARGOCD_ADMIN_PASSWORD "$env" "a generated password" </dev/null
  elif gh secret list --repo "$REPO" --env "$env" --json name --jq '.[].name' | grep -qx ARGOCD_ADMIN_PASSWORD; then
    echo "   ARGOCD_ADMIN_PASSWORD for $env already set, kept"
  else
    password=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)
    secret ARGOCD_ADMIN_PASSWORD "$env" "a generated password" <<<"$password"
    echo "   Argo CD admin password for $env (shown once, store it safely): $password"
  fi
done

echo "== Promotion GitHub App credentials"
if [ "$DRY_RUN" = 1 ]; then
  secret PROMOTER_CLIENT_ID - "--promoter-client-id" </dev/null
  secret PROMOTER_PRIVATE_KEY - "--promoter-key-file" </dev/null
elif [ -n "$PROMOTER_CLIENT_ID" ] && [ -f "$PROMOTER_KEY_FILE" ]; then
  secret PROMOTER_CLIENT_ID - "--promoter-client-id" <<<"$PROMOTER_CLIENT_ID"
  secret PROMOTER_PRIVATE_KEY - "--promoter-key-file" < "$PROMOTER_KEY_FILE"
else
  echo "   skipped: pass --promoter-client-id and --promoter-key-file once the GitHub App exists"
fi

echo "== GitHub Pages from main /"
if [ "$DRY_RUN" = 0 ] && gh api "repos/$REPO/pages" >/dev/null 2>&1; then
  api PUT "repos/$REPO/pages" '{"source":{"branch":"main","path":"/"}}'
else
  api POST "repos/$REPO/pages" '{"source":{"branch":"main","path":"/"}}'
fi

echo "Done."
