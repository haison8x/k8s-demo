#!/usr/bin/env bash
# Promote an app's release one step: copy gitops/apps/<app>/envs/<from>/release.yaml
# to envs/<to>/release.yaml on a new branch and open a pull request.
# Used by the "promote" workflow; GH_TOKEN must belong to the GitHub App so the
# pull request triggers CI and can be approved by a human.
#
#   scripts/promote.sh dev-to-staging|staging-to-prod [APP]    (APP defaults to demo-app)
#
# PROMOTE_LOCAL_ONLY=1 stops after the local commit (used by tests).
set -euo pipefail

case "${1:-}" in
  dev-to-staging) from=dev; to=staging ;;
  staging-to-prod) from=staging; to=prod ;;
  *) echo "usage: $0 dev-to-staging|staging-to-prod [APP]" >&2; exit 2 ;;
esac

app=${2:-demo-app}
if ! [[ "$app" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || [ ! -d "gitops/apps/$app/envs" ]; then
  echo "unknown app '$app': expected a folder gitops/apps/<app>/envs" >&2
  exit 2
fi

src="gitops/apps/$app/envs/$from/release.yaml"
dst="gitops/apps/$app/envs/$to/release.yaml"

if cmp -s "$src" "$dst"; then
  echo "nothing to promote: $app in $to already runs the $from release"
  exit 0
fi

version=$(awk '/^ *APP_VERSION:/ {sub(/^ *APP_VERSION: */, ""); gsub(/["'"'"' ]/, ""); print; exit}' "$src")
if [ -z "$version" ]; then
  version=$(awk '/^ *tag:/ {sub(/^ *tag: */, ""); gsub(/["'"'"' ]/, ""); print; exit}' "$src")
fi
version=${version:-unknown}
branch="promote/$app-$from-to-$to-$(date -u +%Y%m%d%H%M%S)"
title="Promote $app $from to $to ($version)"

git checkout -q -b "$branch"
cp "$src" "$dst"
git add "$dst"
git -c user.name="k8s-demo-promoter[bot]" -c user.email="k8s-demo-promoter[bot]@users.noreply.github.com" \
  commit -q -m "$title"
echo "committed: $title"

if [ "${PROMOTE_LOCAL_ONLY:-0}" = "1" ]; then
  exit 0
fi

git push -q origin "$branch"
gh pr create --base main --head "$branch" --title "$title" --body "$(cat <<EOF
Promotes the $app release from **$from** to **$to** by copying
\`$src\` to \`$dst\`.

- Only the release file changes; environment settings (replicas, host, banner) stay as they are.
- After merge, the $to cluster's Argo CD rolls out the new release.
EOF
)"
