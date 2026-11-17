#!/usr/bin/env bash
# Fetch the admin kubeconfig of one environment into its own file, with the
# context renamed to k8s-demo-<env>. Never merges into ~/.kube/config, so a
# shell only talks to the environment it explicitly selects.
#
#   scripts/get-kubeconfig.sh dev|staging|prod
#   export KUBECONFIG=~/.kube/k8s-demo-prod.kubeconfig
set -euo pipefail

env=${1:-}
case "$env" in
  dev|staging|prod) ;;
  *) echo "usage: $0 dev|staging|prod" >&2; exit 2 ;;
esac

root=$(cd "$(dirname "$0")/.." && pwd)
inventory="$root/ansible/inventories/$env"
# The first host listed in hosts.yml is the first control plane.
first_cp=$(grep -m1 -oE 'ansible_host: [0-9.]+' "$inventory/hosts.yml" | awk '{print $2}')
vip=$(awk '/^kube_vip_address:/ {print $2}' "$inventory/group_vars/all.yml")
user=$(awk '/^ansible_user:/ {print $2}' "$root/ansible/group_vars/all/common.yml")
out_dir="${KUBECONFIG_DIR:-$HOME/.kube}"
out="$out_dir/k8s-demo-$env.kubeconfig"
tmp="$out.tmp"

mkdir -p "$out_dir"
umask 077
echo "source: $user@$first_cp:.kube/config"
if [ -n "${KUBECONFIG_SOURCE:-}" ]; then
  cp "$KUBECONFIG_SOURCE" "$tmp" # tests
else
  scp -q -i "${SSH_KEY:-$HOME/.ssh/k8s-demo/$env}" -o StrictHostKeyChecking=accept-new \
    "$user@$first_cp:.kube/config" "$tmp"
fi

server=$(KUBECONFIG="$tmp" kubectl config view -o jsonpath='{.clusters[0].cluster.server}')
if [ "$server" != "https://$vip:6443" ]; then
  rm -f "$tmp"
  echo "refusing: API server is $server, expected https://$vip:6443 for $env" >&2
  exit 1
fi
context=$(KUBECONFIG="$tmp" kubectl config current-context)
KUBECONFIG="$tmp" kubectl config rename-context "$context" "k8s-demo-$env" >/dev/null
mv "$tmp" "$out"
chmod 600 "$out"
echo "export KUBECONFIG=$out"
