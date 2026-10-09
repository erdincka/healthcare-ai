# Tiltfile for HealthcareAI Frontend: development and testing only.
# The published image and the EzAppConfig deployment never use this file.

# Load .env file
load('ext://dotenv', 'dotenv')
dotenv()

allow_k8s_contexts(os.environ['KUBE_CONTEXT'])
default_registry('registry.' + os.environ['DOMAIN'])

# Building the frontend image
docker_build(
    'healthcare-ai',
    context='./frontend/docker',
    dockerfile='./frontend/docker/Dockerfile',
    # The PCAI nodes are x86_64; build for them even from Apple Silicon.
    platform='linux/amd64',
    # Dev only: Gradio's hot-reload mode. The image's own CMD is production (python app.py).
    entrypoint=['gradio', 'app.py'],
    live_update=[
        # A dependency change needs a full rebuild (the app user cannot install packages).
        fall_back_on(['./frontend/docker/requirements.txt']),
        sync('./frontend/docker', '/app/'),
    ],
)

# Deploying using Helm
# Standardise on Helm charts as per project requirements
k8s_yaml(helm(
    './frontend/helm',
    name='healthcare-ai',
    namespace=os.environ['NAMESPACE'],
    # Inject values if necessary, though mostly handled in values.yaml
    set=[
        'image.repository=healthcare-ai',
        'image.tag=latest',
        'ezua.virtualService.endpoint=healthcare.' + os.environ['DOMAIN']
    ]
))

# Watch for changes in the helm chart as well
watch_file('./frontend/helm')
