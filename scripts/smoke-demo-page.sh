#!/usr/bin/env bash
# Smoke test: serve the demo page template with the pinned nginx image, exactly
# as the cluster does, and check what a visitor sees. Requires Docker.
set -euo pipefail
cd "$(dirname "$0")/.."

image=$(awk '/image: nginx:/ {print $2; exit}' gitops/apps/demo-app/overlays/dev/release.yaml)
template="$PWD/gitops/apps/demo-app/base/default.conf.template"
name="k8sdemo-smoke-$$"
port=18080

# The image is public: use an empty Docker config so no credential helper is needed.
DOCKER_CONFIG=$(mktemp -d)
export DOCKER_CONFIG

cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  rm -rf "$DOCKER_CONFIG"
}
trap cleanup EXIT

docker run -d --name "$name" -p "127.0.0.1:$port:80" \
  -e ENV_NAME=DEV -e ENV_COLOR='#2e7d32' -e APP_VERSION=9.9.9 -e APP_MESSAGE='smoke test message' \
  -v "$template:/etc/nginx/templates/default.conf.template:ro" \
  "$image" >/dev/null

for _ in $(seq 1 30); do
  [ "$(curl -s "http://127.0.0.1:$port/healthz" || true)" = "ok" ] && break
  sleep 1
done

body=$(curl -s "http://127.0.0.1:$port/")
pod=$(docker exec "$name" hostname)

check() {
  if ! grep -qF -- "$1" <<<"$body"; then
    echo "FAIL: page does not contain: $1"
    echo "$body" | head -40
    docker logs "$name" 2>&1 | tail -20
    exit 1
  fi
}

check "<h1>K8s Demo</h1>"
check ">DEV<"
check "#2e7d32"
check "Version 9.9.9"
check "smoke test message"
check "Served by pod: $pod"
if grep -q '\${' <<<"$body"; then
  echo "FAIL: page contains an unsubstituted variable"; grep -n '\${' <<<"$body"; exit 1
fi
echo "smoke test passed (image $image, pod $pod)"
