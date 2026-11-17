#!/usr/bin/env bash
# Smoke test: render demo-app for dev with the base chart, serve the rendered
# page template with the rendered image, exactly as the cluster does, and check
# what a visitor sees. Requires Docker, helm and python with PyYAML.
set -euo pipefail
cd "$(dirname "$0")/.."

name="k8sdemo-smoke-$$"
port=18080
work=$(mktemp -d)

# The image is public: use an empty Docker config so no credential helper is needed.
DOCKER_CONFIG=$(mktemp -d)
export DOCKER_CONFIG

cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  rm -rf "$DOCKER_CONFIG" "$work"
}
trap cleanup EXIT

app=gitops/apps/demo-app
helm template demo-app gitops/charts/base-app --namespace demo \
  -f "$app/values.yaml" -f "$app/envs/dev/env.yaml" -f "$app/envs/dev/release.yaml" > "$work/rendered.yaml"

# Extract the image and the page template from the rendered manifests.
python - "$work" <<'PY'
import pathlib
import sys

import yaml

work = pathlib.Path(sys.argv[1])
docs = [d for d in yaml.safe_load_all((work / "rendered.yaml").read_text()) if d]
dep = next(d for d in docs if d["kind"] == "Deployment")
cm = next(d for d in docs if d["kind"] == "ConfigMap")
(work / "image").write_text(dep["spec"]["template"]["spec"]["containers"][0]["image"])
(work / "default.conf.template").write_text(cm["data"]["default.conf.template"])
PY
image=$(cat "$work/image")

docker run -d --name "$name" -p "127.0.0.1:$port:80" \
  -e ENV_NAME=DEV -e ENV_COLOR='#2e7d32' -e APP_VERSION=9.9.9 -e APP_MESSAGE='smoke test message' \
  -v "$work/default.conf.template:/etc/nginx/templates/default.conf.template:ro" \
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
if grep -qF -- "\${" <<<"$body"; then
  echo "FAIL: page contains an unsubstituted variable"; grep -nF -- "\${" <<<"$body"; exit 1
fi
echo "smoke test passed (image $image, pod $pod)"
