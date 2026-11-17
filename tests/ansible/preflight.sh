#!/usr/bin/env bash
# Pre-flight guard tests: run the guard against fixture inventories and check
# that it accepts the good one and rejects each kind of environment mix-up.
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
export ANSIBLE_CONFIG="$root/ansible/ansible.cfg"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
failures=0

run_case() { # case env -> prints output, returns ansible rc
  mkdir -p "$tmp/$1"
  ansible-playbook -i "$root/tests/ansible/inventories/$1/$2/hosts.yml" \
    "$root/tests/ansible/preflight.yml" -e "env_marker_path=$tmp/$1/env" 2>&1
}

expect_pass() { # case env
  local out
  if ! out=$(run_case "$1" "$2"); then
    echo "FAIL [$1]: expected success"; echo "$out" | tail -20; failures=$((failures + 1)); return
  fi
  echo "ok   [$1] accepted"
}

expect_fail() { # case env message
  local out
  if out=$(run_case "$1" "$2"); then
    echo "FAIL [$1]: expected the guard to fail"; failures=$((failures + 1)); return
  fi
  if ! grep -q -- "$3" <<<"$out"; then
    echo "FAIL [$1]: failed without message '$3'"; echo "$out" | tail -20; failures=$((failures + 1)); return
  fi
  echo "ok   [$1] rejected: $3"
}

expect_pass good prod
if [ "$(cat "$tmp/good/env" 2>/dev/null)" != "prod" ]; then
  echo "FAIL [good]: marker not written with 'prod'"; failures=$((failures + 1))
else
  echo "ok   [good] marker written"
fi
expect_pass good prod # second run reads the marker it wrote
expect_fail wrong-env dev "does not match inventory directory"
expect_fail bad-subnet prod "outside 172.20.0.0/24"
mkdir -p "$tmp/marker-mismatch" && echo staging > "$tmp/marker-mismatch/env"
expect_fail marker-mismatch prod "environment marker"

[ "$failures" -eq 0 ] || { echo "$failures pre-flight test(s) failed"; exit 1; }
