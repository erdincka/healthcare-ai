# Tiltfile for HealthcareAI Frontend

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
    live_update=[
        sync('./frontend/docker', '/app/'),
        run('pip install -r requirements.txt', trigger='./frontend/docker/requirements.txt')
    ]
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
        'ezua.virtualService.endpoint=healthcare-ai.' + os.environ['DOMAIN']
    ]
))

# Watch for changes in the helm chart as well
watch_file('./frontend/helm')
