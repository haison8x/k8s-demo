{{/* Resource name: nameOverride, else the release name. */}}
{{- define "base-app.fullname" -}}
{{- default .Release.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* The environment, validated: rendering fails without a known one. */}}
{{- define "base-app.environment" -}}
{{- $env := required "environment is required (dev, staging or prod)" .Values.environment -}}
{{- if not (has $env (list "dev" "staging" "prod")) -}}
{{- fail (printf "environment must be one of dev, staging, prod (got %q)" $env) -}}
{{- end -}}
{{- $env -}}
{{- end -}}

{{- define "base-app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "base-app.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "base-app.labels" -}}
{{ include "base-app.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
k8sdemo.vn/env: {{ include "base-app.environment" . }}
{{- end -}}

{{- define "base-app.image" -}}
{{- $repo := required "image.repository is required" .Values.image.repository -}}
{{- $tag := required "image.tag is required (set it in release.yaml)" .Values.image.tag -}}
{{- printf "%s:%s" $repo (toString $tag) -}}
{{- end -}}
