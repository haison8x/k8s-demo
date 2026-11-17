# Component versions

Every external component is pinned. To upgrade one, change it where it is pinned (last column), open a pull request for **dev** first, then promote the same change to staging and prod.

Resolved on 2026-11-17.

| Component | Version | Pinned in |
|---|---|---|
| Kubernetes (kubeadm, kubelet, kubectl) | 1.37 (apt channel `v1.37`) | `ansible/group_vars/all/versions.yml` (`kube_minor`) |
| kube-vip | v1.3.1 | `ansible/group_vars/all/versions.yml` (`kube_vip_version`) |
| Calico (tigera-operator) | v3.33.1 | `ansible/group_vars/all/versions.yml` (`calico_version`) |
| Argo CD | v3.6.1 | `gitops/platform/argocd/base/kustomization.yaml` and `ansible/group_vars/all/versions.yml` (`argocd_version`) |
| MetalLB Helm chart | 0.16.2 (app v0.16.2) | `gitops/clusters/<env>/metallb.yaml` |
| F5 NGINX Ingress Controller Helm chart | 2.8.1 (app 5.7.1), repo `https://helm.nginx.com/stable` | `gitops/clusters/<env>/nginx-ingress.yaml` |
| Kyverno Helm chart | 3.10.0 (app v1.20.0) | `gitops/clusters/<env>/kyverno.yaml` |
| Kyverno CLI (tests) | v1.20.0 | `scripts/validate.sh` |
| nginx image (demo app) | 1.31.8-alpine | `gitops/apps/demo-app/overlays/<env>/release.yaml` |
| GitHub Actions runner | 2.338.2 | `ansible/inventories/ops/group_vars/all.yml` |
| kubeconform | v0.8.0 | `.github/workflows/validate.yml` |
| actionlint | 1.7.12 | `.github/workflows/validate.yml` |
| shellcheck | v0.11.0 | `.github/workflows/validate.yml` |
