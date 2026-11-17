#!/usr/bin/env bash
# Install the pinned validation toolchain without root: a Python virtualenv in
# ~/.venvs/k8s-demo and static binaries in ~/.local/bin. Used by CI and by
# anyone who wants to run scripts/validate.sh locally (Linux or WSL).
#
#   bash scripts/install-tools.sh
#   export PATH="$HOME/.venvs/k8s-demo/bin:$HOME/.local/bin:$PATH"
set -euo pipefail

UV_VERSION=0.13.8
KUBECTL_VERSION=v1.37.2
KUBECONFORM_VERSION=v0.8.0
ACTIONLINT_VERSION=1.7.12
SHELLCHECK_VERSION=v0.11.0
KYVERNO_VERSION=v1.20.0
HELM_VERSION=v4.3.2
PYTHON_PACKAGES=(ansible-core==2.21.6 ansible-lint==26.11.0 yamllint==1.38.0 pyyaml==6.0.3
                 passlib==1.7.4 bcrypt==5.0.0 netaddr==1.3.0)

BIN="$HOME/.local/bin"
VENV="$HOME/.venvs/k8s-demo"
mkdir -p "$BIN"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fetch() { curl -sSfL --retry 3 "$1"; }

if ! "$BIN/uv" --version 2>/dev/null | grep -q " $UV_VERSION"; then
  fetch "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz" | tar -xz -C "$tmp"
  install -m 0755 "$tmp/uv-x86_64-unknown-linux-gnu/uv" "$BIN/uv"
fi
[ -x "$VENV/bin/python" ] || "$BIN/uv" venv -q --python 3.12 "$VENV"
"$BIN/uv" pip install -q --python "$VENV/bin/python" "${PYTHON_PACKAGES[@]}"

if ! "$BIN/kubectl" version --client 2>/dev/null | grep -q "$KUBECTL_VERSION"; then
  fetch "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl" > "$tmp/kubectl"
  install -m 0755 "$tmp/kubectl" "$BIN/kubectl"
fi
if ! "$BIN/kubeconform" -v 2>/dev/null | grep -q "$KUBECONFORM_VERSION"; then
  fetch "https://github.com/yannh/kubeconform/releases/download/$KUBECONFORM_VERSION/kubeconform-linux-amd64.tar.gz" | tar -xz -C "$tmp" kubeconform
  install -m 0755 "$tmp/kubeconform" "$BIN/kubeconform"
fi
if ! "$BIN/actionlint" -version 2>/dev/null | grep -q "$ACTIONLINT_VERSION"; then
  fetch "https://github.com/rhysd/actionlint/releases/download/v$ACTIONLINT_VERSION/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz" | tar -xz -C "$tmp" actionlint
  install -m 0755 "$tmp/actionlint" "$BIN/actionlint"
fi
if ! "$BIN/shellcheck" --version 2>/dev/null | grep -q "${SHELLCHECK_VERSION#v}"; then
  fetch "https://github.com/koalaman/shellcheck/releases/download/$SHELLCHECK_VERSION/shellcheck-$SHELLCHECK_VERSION.linux.x86_64.tar.xz" | tar -xJ -C "$tmp"
  install -m 0755 "$tmp/shellcheck-$SHELLCHECK_VERSION/shellcheck" "$BIN/shellcheck"
fi
if ! "$BIN/kyverno" version 2>/dev/null | grep -q "$KYVERNO_VERSION"; then
  fetch "https://github.com/kyverno/kyverno/releases/download/$KYVERNO_VERSION/kyverno-cli_${KYVERNO_VERSION}_linux_x86_64.tar.gz" | tar -xz -C "$tmp" kyverno
  install -m 0755 "$tmp/kyverno" "$BIN/kyverno"
fi
if ! "$BIN/helm" version --short 2>/dev/null | grep -q "$HELM_VERSION"; then
  fetch "https://get.helm.sh/helm-$HELM_VERSION-linux-amd64.tar.gz" | tar -xz -C "$tmp" linux-amd64/helm
  install -m 0755 "$tmp/linux-amd64/helm" "$BIN/helm"
fi

export PATH="$VENV/bin:$BIN:$PATH"
if [ -n "${GITHUB_PATH:-}" ]; then
  echo "$BIN" >> "$GITHUB_PATH"
  echo "$VENV/bin" >> "$GITHUB_PATH"
fi
ansible-galaxy collection install -r "$(dirname "$0")/../ansible/requirements.yml" >/dev/null
echo "toolchain ready: $(ansible --version | head -1)"
