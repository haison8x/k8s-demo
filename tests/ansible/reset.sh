#!/usr/bin/env bash
# reset.yml must refuse to run unless confirm_reset names the environment.
# Only negative cases are exercised: a passing run would wipe this machine.
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
export ANSIBLE_CONFIG="$root/ansible/ansible.cfg"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
failures=0

expect_refusal() { # label extra-args...
  local label=$1 out
  shift
  if out=$(ansible-playbook -i "$root/tests/ansible/inventories/reset/prod/hosts.yml" \
      "$root/ansible/reset.yml" -e ansible_become=false -e "env_marker_path=$tmp/env" "$@" 2>&1); then
    echo "FAIL [$label]: reset.yml ran"; failures=$((failures + 1)); return
  fi
  if ! grep -q "confirm_reset must equal 'prod'" <<<"$out"; then
    echo "FAIL [$label]: refused without the confirmation message"; echo "$out" | tail -15
    failures=$((failures + 1)); return
  fi
  if grep -q "kubeadm reset" <<<"$out"; then
    echo "FAIL [$label]: a destructive task started"; failures=$((failures + 1)); return
  fi
  echo "ok   [$label] refused"
}

expect_refusal "no confirmation"
expect_refusal "confirmation 'yes'" -e confirm_reset=yes
expect_refusal "wrong environment" -e confirm_reset=staging

[ "$failures" -eq 0 ] || { echo "$failures reset test(s) failed"; exit 1; }
