# Dev loop for healthcareai (skill pcai-dev-loop): builds the image, pushes it to a registry the cluster pulls from,
# deploys the chart into a dev namespace under the app's dev hostname and live-syncs source into the pod. The live app
# is never touched: Tilt refuses PCAI's own namespaces and every namespace a PCAI app (EzAppConfig) is installed in,
# where it would take over that release's objects.
#
# Settings come from tilt_config.json (git-ignored; copy tilt_config.example.json):
#   context    kube context to deploy with (Tilt refuses any other)
#   registry   image registry the cluster pulls from, e.g. registry.example.com/dev
#   endpoint   dev hostname, e.g. healthcareai-dev.<domain>
#   namespace  dev namespace (default dev)
#   set        extra Helm values, e.g. ["llm.model=my-model"]
#   force      true takes the app's dev slot over from whoever holds it
# Run: tilt up --context <context>. Stop: tilt down --context <context> (frees the dev slot).
config.define_string('context')
config.define_string('registry')
config.define_string('endpoint')
config.define_string('namespace')
config.define_string_list('set')
config.define_bool('force')
cfg = config.parse()
for key in ['context', 'registry', 'endpoint']:
    if not cfg.get(key):
        fail('set "%s" in tilt_config.json (copy tilt_config.example.json)' % key)

APP = 'healthcareai'
CHART = 'frontend/helm'
DEV_VALUES = 'dev-values.yaml'  # committed dev-only chart values; never used in production
KUBE_CONTEXT = cfg['context']
NAMESPACE = cfg.get('namespace', 'dev')
ENDPOINT = cfg['endpoint']

# ── Guards ──────────────────────────────────────────────────────────────────────────────────────────────────────
PROTECTED = ['default', 'datafabric', 'istio-system', 'keycloak', 'kyverno', 'litellm', 'metallb-system', 'mlflow',
             'mlis', 'monitoring', 'nfs-csi', 'otel-collector', 'superset', 'ui', 'welcome']
PROTECTED_PREFIXES = ['kube', 'ez', 'hpe', 'project-', 'knative', 'nvidia', 'spark', 'token']

allow_k8s_contexts(KUBE_CONTEXT)
if k8s_context() != KUBE_CONTEXT:
    fail('kube context is %s, expected %s: run `tilt up --context %s`' % (k8s_context(), KUBE_CONTEXT, KUBE_CONTEXT))
if NAMESPACE in PROTECTED or [p for p in PROTECTED_PREFIXES if NAMESPACE.startswith(p)]:
    fail('refusing to deploy into protected namespace %s' % NAMESPACE)


def kubectl(args):
    """Runs a read-only kubectl command against the configured context; empty output on error."""
    return str(local('kubectl --context %s %s 2>/dev/null || true' % (KUBE_CONTEXT, args), quiet=True,
                     echo_off=True)).strip()


# Where PCAI apps are installed (EzAppConfig .spec.options.namespace): the live apps, never a dev loop.
live = kubectl("get ezappconfig -o jsonpath='{range .items[*]}{.spec.options.namespace}{\"\\n\"}{end}'").split()
if NAMESPACE in live:
    fail('refusing to deploy into %s: a PCAI app is installed there, and Tilt would take over its objects. Use dev'
         % NAMESPACE)

# One dev slot per app: a ConfigMap names who holds it. `tilt down` deletes it with the rest.
ME = str(local('git config user.email || whoami', quiet=True, echo_off=True)).strip()
SLOT = APP + '-dev-slot'
holder = kubectl("-n %s get configmap %s -o jsonpath='{.data.holder} {.data.since}'" % (NAMESPACE, SLOT)).split(' ')
if holder[0] and holder[0] != ME and not cfg.get('force', False):
    fail(('the %s dev slot is held by %s since %s. Ask them to run `tilt down`, or set "force": true in ' +
          'tilt_config.json to take it over') % (APP, holder[0], holder[1] if len(holder) > 1 else '?'))
since = holder[1] if holder[0] == ME and len(holder) > 1 else str(local('date -u +%FT%TZ', quiet=True)).strip()
k8s_yaml(encode_yaml({
    'apiVersion': 'v1', 'kind': 'ConfigMap',
    'metadata': {'name': SLOT, 'namespace': NAMESPACE,
                 'labels': {'app.kubernetes.io/instance': APP, 'app.kubernetes.io/managed-by': 'tilt'}},
    'data': {'holder': ME, 'since': since, 'endpoint': ENDPOINT},
}))

default_registry(cfg['registry'])

# ── Images ──────────────────────────────────────────────────────────────────────────────────────────────────────
# Do NOT pass `only=` to docker_build: it strips source out of the image. .tiltignore and .dockerignore keep the
# context small instead. An app with several images builds each from its own folder, or from the root with `ignore=`
# for the other images' folders: otherwise any edit matches no sync() of the other images and Tilt rebuilds them all.
#
# The build context is frontend/docker, as for the published image: the chart, Tiltfile and dev values sit outside it,
# so changing them redeploys without a rebuild. The dev target restarts `python app.py` when a synced .py file changes.
docker_build(
    'healthcareai',
    context='frontend/docker',
    dockerfile='frontend/docker/Dockerfile',
    target='dev',
    # The PCAI nodes are x86_64; build for them even from Apple Silicon.
    platform='linux/amd64',
    live_update=[
        fall_back_on(['./frontend/docker/requirements.txt', './frontend/docker/requirements-dev.txt',
                      './frontend/docker/Dockerfile']),
        sync('./frontend/docker/', '/app'),
    ],
)

# ── Chart ───────────────────────────────────────────────────────────────────────────────────────────────────────
k8s_yaml(helm(
    CHART,
    name=APP,
    namespace=NAMESPACE,
    values=[DEV_VALUES] if os.path.exists(DEV_VALUES) else [],
    set=['ezua.virtualService.endpoint=' + ENDPOINT, 'image.repository=healthcareai'] + cfg.get('set', []),
))
k8s_resource(APP, links=[link('https://' + ENDPOINT, 'healthcareai (dev)')])
