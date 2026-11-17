# k8s-demo

Infrastructure as code for three on-premises Kubernetes clusters (dev, staging, prod) run the GitOps way:

- **Ansible** builds each cluster with kubeadm (HA control plane, kube-vip, Calico). It runs from GitHub Actions on a runner inside the LAN.
- **Argo CD** runs in every cluster and reconciles everything else from this repository: MetalLB, F5 NGINX Ingress Controller, Kyverno, Argo CD itself, and the demo app.
- **Promotion** between environments is a button that opens a pull request.

The result is a small nginx app that shows **K8s Demo**, the environment, the release version and the pod that answered:
`http://dev.k8sdemo.vn`, `http://staging.k8sdemo.vn`, `http://k8sdemo.vn`.

**Full guide:** https://haison8x.github.io/k8s-demo/

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
| Node drift detection | `ansible/` (`--check`) | ops runner | **drift** workflow, nightly |
| Promotion dev → staging → prod | `release.yaml` files | **promote** workflow | button, opens a PR |

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

Pod CIDR `10.244.0.0/16`, service CIDR `10.96.0.0/12`. Outbound traffic uses the proxy `proxy.mycompany.com:3128`. Server VLANs use static addresses only (no DHCP).

## Repository layout

```
ansible/
  inventories/{dev,staging,prod,ops}/   hosts and per-environment settings
  roles/                                preflight, common, kube_vip, control_plane, worker, argocd_bootstrap, ops_runner
  site.yml  reset.yml  ops.yml
gitops/
  clusters/<env>/                       Argo CD Applications of one cluster (root app path)
  platform/                             argocd, metallb, nginx-ingress, kyverno
  apps/demo-app/{base,overlays/<env>}   env.yaml = environment settings, release.yaml = promotable release
scripts/                                validate, install-tools, github-setup, get-kubeconfig, promote, env-guard
tests/                                  repository, Ansible, policy and smoke tests
.github/workflows/                      validate, ansible, drift, promote
```

## One-time setup

Work from WSL or Linux, in a clone **inside your Linux home directory** (Ansible ignores `ansible.cfg` in world-writable folders such as `/mnt/c`, and SSH rejects keys with open permissions).

1. **Servers and network.** Ubuntu 24.04 on every node and on the ops VM, addresses as above, user `haison` with passwordless sudo. Put `~/.ssh/k8s-demo/<env>.pub` in `~haison/.ssh/authorized_keys` on the matching servers (`ops.pub` on ops1). Firewall: dev/staging cannot reach prod; ops1 reaches every subnet on SSH; the presenter laptop reaches each ingress IP on port 80 and the prod VIP on 6443.
2. **GitHub App** `k8s-demo-promoter` (Settings → Developer settings → GitHub Apps): repository permissions *Contents* and *Pull requests*: read and write. Install it on this repository, note its Client ID and download a private key.
3. **GitHub settings:** `gh auth login`, then
   `bash scripts/github-setup.sh --promoter-client-id <CLIENT_ID> --promoter-key-file <key.pem>`.
   It creates the ruleset, environments, secrets and Pages, and prints each Argo CD admin password once.
4. **Runner:**
   ```bash
   bash scripts/install-tools.sh && export PATH="$HOME/.venvs/k8s-demo/bin:$HOME/.local/bin:$PATH"
   ansible-playbook -i ansible/inventories/ops/hosts.yml ansible/ops.yml --private-key ~/.ssh/k8s-demo/ops \
     -e runner_registration_token=$(gh api -X POST repos/haison8x/k8s-demo/actions/runners/registration-token --jq .token)
   ```
5. **Build the clusters:** Actions → **ansible** → env `dev`, playbook `site`. Then `staging`, then `prod` (approve the run).
6. **Name resolution** on the presenter laptop (`C:\Windows\System32\drivers\etc\hosts`) or LAN DNS:
   ```
   172.20.2.200 dev.k8sdemo.vn argocd.dev.k8sdemo.vn
   172.20.1.200 staging.k8sdemo.vn argocd.staging.k8sdemo.vn
   172.20.0.200 k8sdemo.vn argocd.k8sdemo.vn
   ```
7. **kubectl (optional):** `scripts/get-kubeconfig.sh prod` then `export KUBECONFIG=~/.kube/k8s-demo-prod.kubeconfig`.

## Everyday operations

| I want to… | Do this | What happens |
|---|---|---|
| Change the app in dev | Edit `gitops/apps/demo-app/overlays/dev/release.yaml`, open a PR | CI validates; after merge dev's Argo CD rolls it out |
| Promote | Actions → **promote** → `dev-to-staging` or `staging-to-prod` | The bot opens a PR; a code owner approves; merge deploys |
| Change environment settings | Edit `overlays/<env>/env.yaml` (replicas, host, banner) | Never promoted |
| Upgrade a platform component | Change the version in `gitops/clusters/dev/…`, then staging, then prod (one PR each) | Argo CD upgrades that cluster |
| Add a node | Add it to `ansible/inventories/<env>/hosts.yml`, merge, run **ansible** with limit `<first-cp>,<new-node>` | Node joins |
| Rebuild an environment | **ansible** with playbook `reset` and confirm = env name, then `site` | Cluster wiped and rebuilt |

One pull request may change **one environment only**; shared paths (`base/`, `gitops/platform/`, roles, workflows) need a code owner review because they reach prod too.

## Guard rails

Subnet per environment; no default inventory; a pre-flight check (inventory ↔ subnet ↔ `/etc/k8s-demo/env` marker); a free-IP check before the first `kubeadm init`; per-environment SSH keys in GitHub environments; prod approval; env-prefixed hostnames and separate kubeconfig files; Argo CD banners; a Kyverno policy that rejects resources labelled for another environment; CI checks (`scripts/env-guard.py`) that keep hosts, IPs, proxy settings and Application paths consistent with each environment.

## Validate locally

```bash
bash scripts/install-tools.sh
export PATH="$HOME/.venvs/k8s-demo/bin:$HOME/.local/bin:$PATH"
bash scripts/validate.sh        # needs Docker for the page smoke test
```

Component versions are listed in [docs/VERSIONS.md](docs/VERSIONS.md).
