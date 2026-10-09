# Frontend

- `docker/`: the Gradio application and its production Dockerfile. Unit tests live in
  `docker/tests` and run inside a container built from the Dockerfile (see the root readme).
- `helm/`: the Helm chart. `helm package frontend/helm` produces `healthcareai-<version>.tgz`, which
  you import into HPE Private Cloud AI through AI Essentials → **Import Framework**. The repository
  root carries the current packaged chart (`healthcareai-0.3.1.tgz`) and `healthcare-ezapp.yaml`
  as the reference for the import values.

The chart sets the `hpe-ezua/app` and `hpe-ezua/type` labels on every resource itself, so no
Kyverno labelling policy is required.
