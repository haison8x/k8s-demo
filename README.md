# k8s-demo

Infrastructure as code for three on-premises Kubernetes clusters (dev, staging, prod) run the GitOps way:

- **Ansible** builds each cluster with kubeadm (HA control plane, kube-vip, Calico). It runs from GitHub Actions on a runner inside the LAN.
- **Argo CD** runs in every cluster and reconciles everything else from this repository: MetalLB, F5 NGINX Ingress Controller, Kyverno, Argo CD itself, and the demo app.
- **Promotion** between environments is a button that opens a pull request.

The result is a small nginx app that shows **K8s Demo**, the environment, the release version and the pod that answered:
`http://dev.k8sdemo.vn`, `http://staging.k8sdemo.vn`, `http://k8sdemo.vn`.

**Full guide:** https://haison8x.github.io/k8s-demo/ (the same content as this file, as a web page; it goes live once `scripts/github-setup.sh` has enabled GitHub Pages).

## Contents

1. [Current status](#current-status)
2. [Read this first: the ideas in two minutes](#read-this-first-the-ideas-in-two-minutes)
3. [Architecture](#architecture)
4. [Environments](#environments)
5. [Repository layout](#repository-layout)
6. [Automation switch](#automation-switch)
7. [Before you start](#before-you-start)
8. [One-time setup](#one-time-setup)
9. [Check that it works](#check-that-it-works)
10. [Everyday operations](#everyday-operations)
11. [Promotion](#promotion)
12. [Secrets and access](#secrets-and-access)
13. [Guard rails](#guard-rails)
14. [Contributing](#contributing)
15. [Running Ansible by hand](#running-ansible-by-hand)
16. [Demo runbook](#demo-runbook)
17. [Troubleshooting](#troubleshooting)
18. [Known limitations](#known-limitations)

## Current status

| Item | State |
|---|---|
| Code on `main` | Complete; every check in `scripts/validate.sh` passes |
| GitHub Actions | **Off**: the variable `AUTOMATION_ENABLED` is not set (see [Automation switch](#automation-switch)) |
| GitHub settings (ruleset, environments, secrets, Pages) | Not applied yet: run `scripts/github-setup.sh` |
| GitHub App `k8s-demo-promoter` | Not created yet |
| Servers, ops runner, clusters | Not built yet |
| SSH keys | Placeholder keys exist only on the owner's workstation (`~/.ssh/k8s-demo/`); replace them before use |

Nothing touches a server until a person turns automation on **and** presses the **ansible** button.

## Read this first: the ideas in two minutes

| Term | What it means here |
|---|---|
| **IaC / GitOps** | Every server setting and every Kubernetes object is a file in this repository. You change the system by merging a pull request, never by typing commands on a server. |
| **kubeadm** | The official tool that turns plain Ubuntu machines into a Kubernetes cluster. Ansible calls it. |
| **Control plane / worker** | Control planes run the Kubernetes brain (API server, etcd, scheduler); workers run the applications. Three control planes survive the loss of one. |
| **kube-vip, VIP** | A virtual IP (`.100` in each subnet) that always points at a healthy control plane, so `kubectl` keeps working when one control plane is down. |
| **Calico** | The pod network (CNI): gives each pod an address in `10.244.0.0/16` and routes traffic between nodes. |
| **MetalLB** | Gives `LoadBalancer` services a real LAN address from the pool `.200–.229`, which cloud providers would normally do. |
| **F5 NGINX Ingress Controller** | The single entry point on `.200`: routes `http://<host>` to the right service by host name. |
| **Argo CD** | Runs inside each cluster, watches this repository and makes the cluster match it. It also undoes manual changes (self-healing). |
| **App of apps, sync waves** | Ansible creates one *root* Argo CD Application per cluster pointing at `gitops/clusters/<env>/`; that folder lists the other Applications, installed in order (wave 0, 1, 2…). |
| **Kustomize overlay** | `base/` holds what every environment shares; `overlays/<env>/` holds the differences. |
| **Kyverno** | A policy engine. Here it rejects any object labelled for a different environment than the cluster's own. |
| **Self-hosted runner** | A small VM in the LAN (`ops1`) that runs GitHub Actions jobs, because GitHub's own runners cannot reach private servers. |
| **GitHub environment** | A named set of secrets plus rules (for example, "prod needs an approval") that a workflow job must pass through. |
| **CODEOWNERS, ruleset** | GitHub rules: changes to staging, prod and shared files need a review from a listed owner; `main` only changes through pull requests with a green **validate** check. |

## Architecture

```
                 GitHub: haison8x/k8s-demo (main)
      ┌──────────────────────┼─────────────────────────────┐
      │ validate (GitHub-     │ ansible / drift              │ Argo CD in each cluster
      │ hosted, every PR)     │ (self-hosted runner,         │ pulls gitops/clusters/<env>
      │                       │  ops1 172.20.9.5)            │ through the proxy
      ▼                       ▼ SSH                          ▼
  lint, schemas,      ┌──────────────┬──────────────┬──────────────┐
  policy tests,       │ dev          │ staging      │ prod         │
  env guards          │ 172.20.2.0/24│ 172.20.1.0/24│ 172.20.0.0/24│
                      └──────────────┴──────────────┴──────────────┘
```

| Layer | Lives in | Applied by | Trigger |
|---|---|---|---|
| Nodes, kubeadm, kube-vip, Calico, first Argo CD install | `ansible/` | Ansible on the ops runner | **ansible** workflow (button); prod needs approval |
| Everything inside the clusters | `gitops/` | each cluster's Argo CD | merge to `main` |
| Node drift detection | `ansible/` (`--check`) | ops runner | **drift** workflow, nightly 02:00 (Asia/Ho_Chi_Minh) |
| Promotion dev → staging → prod | `release.yaml` files | **promote** workflow | button, opens a PR |
| GitHub settings | `scripts/github-setup.sh` | the repository owner | once |

### What `ansible/site.yml` does, in order

1. **Pre-flight** (every node): the inventory folder, the node's subnet and the marker file `/etc/k8s-demo/env` must all name the same environment, otherwise the whole run stops before anything changes.
2. **Common** (every node): proxy for apt and containerd, hostname, `/etc/hosts`, swap off, kernel modules and sysctl, containerd with the systemd cgroup driver, kubelet/kubeadm/kubectl from `pkgs.k8s.io` (held at the pinned minor version).
3. **Control plane**: on a new cluster, checks that the VIP and the MetalLB pool are unused; starts kube-vip; `kubeadm init` on the first control plane; installs Calico; joins the other control planes. A node whose earlier join failed halfway is reset and joined again.
4. **Workers**: join the cluster.
5. **Hand-over to Argo CD** (first control plane): writes `kube-system/cluster-identity`, installs Argo CD if it is missing, sets the admin password from the GitHub secret, and applies the root Application. From here on Argo CD owns everything inside the cluster.

Running it again is safe: finished steps are skipped.

### What Argo CD installs, in order

| Wave | Application | Source |
|---|---|---|
| 0 | `metallb` | Helm chart `metallb` 0.16.2 |
| 1 | `metallb-config` | `gitops/platform/metallb/config/overlays/<env>` (address pool) |
| 2 | `kyverno` | Helm chart `kyverno` 3.10.0 + `gitops/platform/kyverno/values.yaml` |
| 3 | `kyverno-policies` | `gitops/platform/kyverno/policies` |
| 4 | `nginx-ingress` | Helm chart `nginx-ingress` 2.8.1 + `gitops/platform/nginx-ingress/values*.yaml` |
| 5 | `argocd` | `gitops/platform/argocd/overlays/<env>` (Argo CD manages itself) |
| 6 | `demo-app` | `gitops/apps/demo-app/overlays/<env>` |

Every Application has automatic sync with `prune` and `selfHeal`: what is in Git is what runs.

### How a change reaches a cluster

```
edit a file → pull request → validate (CI) → review if needed → merge to main
→ Argo CD in the matching cluster notices (about 3 minutes, or press Refresh) → cluster updated
```

## Environments

| | dev | staging | prod |
|---|---|---|---|
| Subnet | 172.20.2.0/24 | 172.20.1.0/24 | 172.20.0.0/24 |
| Nodes | dev-cp1 .5, dev-worker1 .6 | stg-cp1..3 .5–.7, stg-worker1..2 .8–.9 | prod-cp1..3 .5–.7, prod-worker1..3 .8–.10 |
| API VIP (kube-vip) | 172.20.2.100 | 172.20.1.100 | 172.20.0.100 |
| MetalLB pool | .200–.229 | .200–.229 | .200–.229 |
| Ingress IP | 172.20.2.200 | 172.20.1.200 | 172.20.0.200 |
| App | dev.k8sdemo.vn | staging.k8sdemo.vn | k8sdemo.vn |
| Argo CD | argocd.dev.k8sdemo.vn | argocd.staging.k8sdemo.vn | argocd.k8sdemo.vn |
| Demo replicas | 1 | 2 | 3 |

Pod CIDR `10.244.0.0/16`, service CIDR `10.96.0.0/12` (chosen so they do not overlap the office LAN, which uses 192.168.x.x). Outbound traffic uses the proxy `proxy.mycompany.com:3128`. Server VLANs use static addresses only (no DHCP). The ops runner `ops1` is `172.20.9.5`.

### Servers to prepare

| Role | Count | Suggested size |
|---|---|---|
| Control planes | 1 dev + 3 staging + 3 prod = 7 | 2 vCPU, 4 GB RAM, 40 GB disk |
| Workers | 1 dev + 2 staging + 3 prod = 6 | 2 vCPU, 4 GB RAM, 40 GB disk |
| Ops runner `ops1` | 1 | 2 vCPU, 2 GB RAM, 20 GB disk |

kubeadm refuses to run with less than 2 vCPU and 2 GB RAM. All servers run Ubuntu 24.04 (fresh install, nothing else on it).

## Repository layout

```
ansible/
  ansible.cfg, requirements.yml         Ansible settings and collections (no default inventory on purpose)
  group_vars/all/common.yml             settings shared by every environment (SSH user, CIDRs, proxy, Git repo)
  group_vars/all/versions.yml           Kubernetes, kube-vip and Calico versions
  inventories/<env>/hosts.yml           the nodes of one environment
  inventories/<env>/group_vars/all.yml  subnet, VIP, MetalLB range, proxy, host names of one environment
  inventories/ops/                      the runner VM
  roles/                                preflight, common, kube_vip, control_plane, worker, argocd_bootstrap, ops_runner
  site.yml  reset.yml  ops.yml          build/converge, wipe, set up the runner
gitops/
  clusters/<env>/                       Argo CD Applications of one cluster (root app path)
  platform/argocd/                      Argo CD install (base) + per-environment overlay (banner, proxy, ingress)
  platform/metallb/config/              address pool per environment
  platform/nginx-ingress/               Helm values (+ fixed ingress IP per environment)
  platform/kyverno/                     Helm values and the environment policy
  apps/demo-app/base/                   namespace, deployment, service, ingress, nginx page template
  apps/demo-app/overlays/<env>/         env.yaml = environment settings, release.yaml = promotable release
scripts/
  validate.sh                           every check CI runs
  install-tools.sh                      pinned toolchain in ~/.venvs/k8s-demo and ~/.local/bin (no sudo)
  github-setup.sh                       one-time GitHub settings
  get-kubeconfig.sh                     fetch one environment's kubeconfig into its own file
  promote.sh                            used by the promote workflow
  env-guard.py                          cross-checks inventories, overlays and pull request diffs
  smoke-demo-page.sh                    renders the demo page in Docker
tests/                                  repository, Ansible, policy and smoke tests
.github/workflows/                      validate, ansible, drift, promote
.github/CODEOWNERS                      who must review which paths
docs/VERSIONS.md                        every pinned version and where it is pinned
```

## Automation switch

Every workflow (validate, ansible, drift, promote) is **off** until the repository variable `AUTOMATION_ENABLED` is `true`. Pushing the repository runs nothing; skipped jobs count as passed checks.

```bash
gh variable set AUTOMATION_ENABLED --body true --repo haison8x/k8s-demo   # on
gh variable delete AUTOMATION_ENABLED --repo haison8x/k8s-demo           # off
```

(Or Settings → Secrets and variables → Actions → Variables.) Turning it off also stops the nightly drift check; it does not stop Argo CD, which keeps syncing the clusters from `main`.

## Before you start

### Access you need

- Admin rights on the GitHub repository `haison8x/k8s-demo` (for `github-setup.sh` and the GitHub App), or write access to contribute.
- SSH access as user `haison` (passwordless sudo) to the servers of the environment you work on.
- A workstation in the LAN: Windows with **WSL2 (Ubuntu)**, or Linux.

### Tools on your workstation

```bash
sudo apt-get install -y git curl openssl python3   # basic tools (once)
# GitHub CLI: https://cli.github.com  then:
gh auth login
git clone https://github.com/haison8x/k8s-demo.git ~/k8s-demo && cd ~/k8s-demo
bash scripts/install-tools.sh                     # Ansible, kubectl, linters... pinned, no sudo
export PATH="$HOME/.venvs/k8s-demo/bin:$HOME/.local/bin:$PATH"   # add this line to ~/.bashrc
```

Clone **inside your Linux home directory**, not under `/mnt/c`: Ansible ignores `ansible.cfg` in world-writable folders, and SSH rejects private keys with open permissions. Docker is only needed for the page smoke test in `scripts/validate.sh`.

### Values you may need to change

All values are plain text; CI fails when two files disagree, so change every place in one pull request.

| Value | Where |
|---|---|
| SSH user (`haison`) | `ansible/group_vars/all/common.yml` |
| Node names and addresses | `ansible/inventories/<env>/hosts.yml` |
| Subnet, VIP, MetalLB range, ingress IP | `ansible/inventories/<env>/group_vars/all.yml`, `gitops/platform/metallb/config/overlays/<env>/ip-pool.yaml`, `gitops/platform/nginx-ingress/values-<env>.yaml` |
| Proxy | `ansible/inventories/<env>/group_vars/all.yml`, `ansible/inventories/ops/group_vars/all.yml`, `gitops/platform/argocd/overlays/<env>/proxy-env-*.yaml` |
| Host names (`*.k8sdemo.vn`) | `ansible/inventories/<env>/group_vars/all.yml`, `gitops/apps/demo-app/overlays/<env>/env.yaml`, `gitops/platform/argocd/overlays/<env>/` |
| Reviewers (`haison8x`, `haison9x`) | `.github/CODEOWNERS`, `scripts/github-setup.sh` (`REVIEWERS`) |
| Repository URL | `ansible/group_vars/all/common.yml`, `gitops/clusters/<env>/*.yaml`, `ansible/inventories/ops/group_vars/all.yml`, `scripts/github-setup.sh` (`REPO`) |
| Versions | see `docs/VERSIONS.md` |

### What the proxy must allow

`pkgs.k8s.io` and the Ubuntu mirrors (packages), `github.com`, `raw.githubusercontent.com` and `objects.githubusercontent.com` (Git, Calico and Argo CD manifests, the runner), the Helm repositories `metallb.github.io`, `kyverno.github.io`, `helm.nginx.com`, and the image registries `registry.k8s.io`, `quay.io`, `ghcr.io`, `docker.io` (`registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com`), `reg.kyverno.io`, `public.ecr.aws`. The ops runner also needs `api.github.com` and `*.actions.githubusercontent.com`.

## One-time setup

Do the steps in this order. Steps 1–5 change nothing on a server; step 7 builds the clusters.

1. **SSH keys.** One key pair per environment plus one for the runner. Replace the placeholder keys:
   ```bash
   mkdir -p ~/.ssh/k8s-demo && chmod 700 ~/.ssh/k8s-demo
   for k in dev staging prod ops; do ssh-keygen -t ed25519 -N "" -C "k8s-demo-$k" -f ~/.ssh/k8s-demo/$k; done
   ```
   The private keys never go into Git; `github-setup.sh` copies them into GitHub environment secrets.
2. **Servers and network.** Ubuntu 24.04 on every node and on the ops VM, addresses as above, user `haison` with passwordless sudo. Put `~/.ssh/k8s-demo/<env>.pub` in `~haison/.ssh/authorized_keys` on the matching servers (`ops.pub` on ops1), for example `ssh-copy-id -i ~/.ssh/k8s-demo/dev.pub haison@172.20.2.5`. Firewall: dev/staging cannot reach prod; ops1 reaches every subnet on SSH; the presenter laptop reaches each ingress IP on port 80 and the prod VIP on 6443. Make sure nothing uses the VIP (`.100`) or the MetalLB range (`.200–.229`) of each subnet, and that the nodes of one environment share one layer-2 network (kube-vip and MetalLB answer ARP).
3. **GitHub App** `k8s-demo-promoter` (it opens promotion pull requests, because pull requests opened by the default workflow token do not start CI):
   1. GitHub → your avatar → Settings → Developer settings → GitHub Apps → **New GitHub App**.
   2. Name `k8s-demo-promoter`, homepage `https://github.com/haison8x/k8s-demo`, untick **Webhook → Active**.
   3. Repository permissions: *Contents* **Read and write**, *Pull requests* **Read and write** (Metadata read-only is added automatically).
   4. "Where can this GitHub App be installed?": **Only on this account**. Create it.
   5. Note the **Client ID**; **Generate a private key** (a `.pem` file is downloaded).
   6. **Install App** → only the repository `k8s-demo`.
4. **GitHub settings:** preview first, then apply:
   ```bash
   bash scripts/github-setup.sh --dry-run
   bash scripts/github-setup.sh --promoter-client-id <CLIENT_ID> --promoter-key-file <key.pem>
   ```
   It sets the read-only workflow token and fork approval, creates the `main-protection` ruleset, invites `haison9x` as a collaborator with write access (accept the invitation), creates the environments `dev`, `staging`, `prod` and `dev-drift`, `staging-drift`, `prod-drift` (prod needs an approval), stores the secrets and enables GitHub Pages. It prints each environment's Argo CD admin password **once**: store them in your password manager. It is safe to run again; existing passwords are kept. Delete the downloaded `.pem` afterwards.
5. **Runner:**
   ```bash
   ansible-playbook -i ansible/inventories/ops/hosts.yml ansible/ops.yml --private-key ~/.ssh/k8s-demo/ops \
     -e runner_registration_token=$(gh api -X POST repos/haison8x/k8s-demo/actions/runners/registration-token --jq .token)
   ```
   ops1 then appears under Settings → Actions → Runners with the label `k8s-demo-ops`.
6. **Turn automation on:** `gh variable set AUTOMATION_ENABLED --body true --repo haison8x/k8s-demo`.
7. **Build the clusters:** Actions → **ansible** → Run workflow → env `dev`, playbook `site`. Check dev (next section), then `staging`, then `prod` (approve the run). Expect roughly 15–30 minutes for a first build.
8. **Name resolution** on the presenter laptop (`C:\Windows\System32\drivers\etc\hosts`, edited as administrator) or LAN DNS:
   ```
   172.20.2.200 dev.k8sdemo.vn argocd.dev.k8sdemo.vn
   172.20.1.200 staging.k8sdemo.vn argocd.staging.k8sdemo.vn
   172.20.0.200 k8sdemo.vn argocd.k8sdemo.vn
   ```
9. **kubectl (optional):** `scripts/get-kubeconfig.sh prod` then `export KUBECONFIG=~/.kube/k8s-demo-prod.kubeconfig`. Each environment gets its own file and context `k8s-demo-<env>`; nothing is merged into `~/.kube/config`.
10. **Argo CD UI:** `http://argocd.<env>.k8sdemo.vn` (prod: `http://argocd.k8sdemo.vn`), user `admin`, password from step 4.

## Check that it works

```bash
export KUBECONFIG=~/.kube/k8s-demo-dev.kubeconfig
kubectl get nodes                                  # every node Ready
kubectl get pods -A | grep -vE 'Running|Completed' # nothing left but the header
kubectl -n argocd get applications                 # every application Synced and Healthy
kubectl get svc -A | grep LoadBalancer             # nginx-ingress has EXTERNAL-IP 172.20.2.200
curl -H 'Host: dev.k8sdemo.vn' http://172.20.2.200 # the K8s Demo page
```

The page shows the environment banner, **K8s Demo**, the release version and message, and the name of the pod that answered.

## Everyday operations

| I want to… | Do this | What happens |
|---|---|---|
| Change the app in dev | Edit `gitops/apps/demo-app/overlays/dev/release.yaml`, open a PR | CI validates; after merge dev's Argo CD rolls it out |
| Promote | Actions → **promote** → `dev-to-staging` or `staging-to-prod` | The bot opens a PR; a code owner approves; merge deploys |
| Change environment settings | Edit `overlays/<env>/env.yaml` (replicas, host, banner) | Never promoted |
| Upgrade a platform component | Change the version in `gitops/clusters/dev/…`, then staging, then prod (one PR each) | Argo CD upgrades that cluster |
| Add a node | Add it to `ansible/inventories/<env>/hosts.yml`, merge, run **ansible** with limit `<first-cp>,<new-node>` | Node joins |
| Rebuild an environment | **ansible** with playbook `reset` and confirm = env name, then `site` | Cluster wiped and rebuilt |
| Investigate drift | Open the failed **drift** run; the diff names the host and file | Re-run **ansible** `site`, or commit the change |
| Pause all automation | `gh variable delete AUTOMATION_ENABLED --repo haison8x/k8s-demo` | Workflows are skipped; Argo CD keeps syncing |

`APP_MESSAGE` in `release.yaml` must not contain quotes, `$`, `;`, braces or backslashes (it is inserted into the nginx configuration).

## Promotion

Each environment's overlay has two files. `env.yaml` holds what belongs to the environment (replicas, host name, banner colour) and is never promoted. `release.yaml` holds what is being released (the image, `APP_VERSION`, `APP_MESSAGE`) and is copied unchanged to the next environment.

```
edit dev release.yaml → PR, CI green, merge → dev updates
→ promote dev-to-staging → bot PR, code owner approves, merge → staging updates
→ promote staging-to-prod → bot PR, code owner approves, merge → prod updates
```

Changes to `base/`, `gitops/platform/`, roles or workflows reach every environment at once, so they always need a code owner review. Keep anything that should roll out gradually in `release.yaml` or in the per-environment Application files.

## Secrets and access

| Secret | Stored in | Used by |
|---|---|---|
| `SSH_PRIVATE_KEY` | environments `dev`, `staging`, `prod` and their `-drift` twins (one key per environment) | **ansible**, **drift** |
| `ARGOCD_ADMIN_PASSWORD` | environments `dev`, `staging`, `prod` | **ansible**, first build only |
| `PROMOTER_CLIENT_ID`, `PROMOTER_PRIVATE_KEY` | repository secrets | **promote** |

| Who | Can |
|---|---|
| Anyone (public repository) | read the code and the workflow logs; open pull requests from forks (their workflows wait for approval) |
| `haison8x`, `haison9x` (code owners) | approve changes to staging, prod and shared paths; approve prod **ansible** runs |
| A collaborator with write access | open pull requests; merge dev-only changes once **validate** is green |

Workflow logs are public: secrets are masked and never printed, and admin kubeconfigs are never shown in a diff. Never commit a private key, a kubeconfig or a password (`.gitignore` blocks the usual file names).

## Guard rails

Subnet per environment; no default inventory; a pre-flight check (inventory ↔ subnet ↔ `/etc/k8s-demo/env` marker); a free-IP check before the first `kubeadm init`; per-environment SSH keys in GitHub environments; prod approval; env-prefixed hostnames and separate kubeconfig files; Argo CD banners; a Kyverno policy that rejects resources labelled for another environment; CI checks (`scripts/env-guard.py`) that keep hosts, IPs, proxy settings and Application paths consistent with each environment; one environment per pull request; `reset` requires typing the environment name.

## Contributing

1. Create a branch: `git switch -c <short-name>`.
2. Change **one environment** per pull request (shared paths are fine on their own).
3. Run the checks locally:
   ```bash
   bash scripts/validate.sh        # needs Docker for the page smoke test
   ```
   It runs yamllint, actionlint, shellcheck, Ansible syntax and lint, the pre-flight and reset tests, the Kyverno policy tests, the page smoke test, the environment guard and the repository tests.
4. Push and open a pull request. **validate** must be green (when automation is on); staging, prod and shared paths need a code owner's approval.
5. After merge, watch the change in that environment's Argo CD.

Write everything in English. Component versions are listed in [docs/VERSIONS.md](docs/VERSIONS.md).

## Running Ansible by hand

For debugging only; normal runs go through the **ansible** workflow, which adds the approval and the audit trail. From your clone:

```bash
export ARGOCD_ADMIN_PASSWORD='<the password of this environment>'   # only read on the first build
ansible-galaxy collection install -r ansible/requirements.yml
cd ansible
ansible-playbook -i inventories/dev/hosts.yml site.yml --private-key ~/.ssh/k8s-demo/dev --check --diff   # dry run
ansible-playbook -i inventories/dev/hosts.yml site.yml --private-key ~/.ssh/k8s-demo/dev                  # apply
ansible-playbook -i inventories/dev/hosts.yml reset.yml --private-key ~/.ssh/k8s-demo/dev -e confirm_reset=dev  # wipe
```

## Demo runbook

1. **The three clusters.** Open `http://argocd.dev.k8sdemo.vn`, `http://argocd.staging.k8sdemo.vn` and `http://argocd.k8sdemo.vn`: every application is Synced and Healthy; note the environment banners.
2. **The app.** Open the three app URLs. Refresh prod a few times: the pod name changes between three pods on three workers.
3. **A change in dev.** Edit `APP_MESSAGE` in `gitops/apps/demo-app/overlays/dev/release.yaml`, open a PR, merge after CI is green. Watch dev's Argo CD roll the pods and the page change.
4. **Promotion.** Actions → **promote** → `dev-to-staging`. Show the bot's PR containing a single file, approve, merge. Repeat with `staging-to-prod`.
5. **Guard rails.** Open a PR that edits both the dev and prod overlays: the **validate** check fails. On prod, try `kubectl -n demo create configmap unlabelled --from-literal=x=1`: the cluster denies it.
6. **Self-healing.** `kubectl -n demo scale deployment demo-app --replicas=1` on prod: Argo CD puts it back to three.
7. **High availability.** Power off `prod-cp1`: `kubectl get nodes` still answers through `172.20.0.100`. Power off a worker: its pod is rescheduled and the page keeps answering.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| A workflow shows **skipped** | Automation is off: set `AUTOMATION_ENABLED` to `true`. **ansible**, **drift** and **promote** also only run from `main`. |
| The **ansible** run waits forever | The runner ops1 is offline (Settings → Actions → Runners) or the prod run waits for approval (review button on the run page). |
| Pre-flight fails: "environment marker … says 'x' but this run targets 'y'" or "… is outside 172.20.x.0/24" | You chose the wrong environment, or the server was reused from another one. Check the inventory; to reuse a server, run `reset` in its old environment first. |
| "IP … is already in use on the network" on the first build | Something answers on the VIP or a MetalLB address. Free it, or change the addresses in the inventory, `ip-pool.yaml` and `values-<env>.yaml` in one PR. |
| `apt` or image pulls time out | The proxy blocks a host (see [What the proxy must allow](#what-the-proxy-must-allow)). `kubectl get pods -A` shows `ImagePullBackOff` with the image name. |
| Argo CD cannot fetch the repository or a chart | Check `gitops/platform/argocd/overlays/<env>/proxy-env-*.yaml`; they must match the inventory (CI checks this). Internal names such as `.svc` and the cluster ranges must stay in `NO_PROXY`. |
| An Application stays OutOfSync or Degraded | Open it in Argo CD; the event list names the failing object. Later waves wait for earlier ones to be Healthy. |
| A sync is denied by Kyverno | The resource's `k8sdemo.vn/env` label does not match the cluster. Check that the Application points at the right overlay. |
| The drift run fails | Someone changed a node by hand. The run's diff names the host and file. Re-run **ansible** `site` to restore it, or commit the change if it should stay. |
| `http://k8sdemo.vn` does not open | Check the hosts file entry, then `curl -H 'Host: k8sdemo.vn' http://172.20.0.200`. |
| Lost the Argo CD admin password | Patch `argocd-secret` in that cluster with a new bcrypt hash (for example `htpasswd -nbBC 10 "" '<new password>' \| tr -d ':\n'`, package `apache2-utils`) in the key `admin.password`, then restart `argocd-server`. Also update the environment secret, although it is only read on the first build. |
| **validate** says "this change touches more than one environment" | Split it: one PR per environment, shared files separately. |

## Known limitations

- HTTP only: no TLS, no public DNS; access from the LAN through a hosts file or LAN DNS.
- No etcd backups, monitoring or log collection.
- Kyverno runs one admission replica: while that pod restarts, writes to the `demo` namespace are briefly refused.
- Changing `kube_minor` or `calico_version` does not upgrade a running cluster; upgrades are a manual, planned operation (or `reset` + `site`).
- Changing `ARGOCD_ADMIN_PASSWORD` after the first build has no effect.
- On a host built before the environment marker existed, the first drift run reports the marker as a change.
- The Kubernetes patch version and containerd come from the latest packages of their channels; only the minor version is pinned.
