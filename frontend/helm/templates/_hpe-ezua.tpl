{{/*
HPE Private Cloud AI (EZUA) labels. The platform uses them to attribute pods
to the imported application. They are set directly on every resource in this
chart, so no Kyverno mutation policy is needed.
*/}}
{{- define "hpe-ezua.labels" -}}
hpe-ezua/app: {{ .Release.Name }}
hpe-ezua/type: vendor-service
{{- end }}

{{/*
Common labels for every resource in the chart.
*/}}
{{- define "healthcareai.labels" -}}
app: {{ .Release.Name }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{ include "hpe-ezua.labels" . }}
{{- end }}
