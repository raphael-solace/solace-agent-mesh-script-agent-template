# Deployment

This template supports two deployment modes:

- **Kubernetes** — build a Docker image and deploy via the `sam-agent` Helm chart
- **Local / whl install** — install `solace-agent-mesh` via pip and run with `sam run`

Both modes use the same config file (`examples/script-agent-config.yaml`).

---

## Option A: Local / whl install

### 1. Install dependencies

```bash
pip install solace-agent-mesh            # or the enterprise .whl
pip install /path/to/this-template       # installs the sam_script_agent package
```

### 2. Set up your project

```
my-project/
├── configs/
│   └── script-agent-config.yaml   # copy from examples/, adjust as needed
├── user_scripts/
│   ├── __init__.py
│   └── normalize_items.py         # your script(s)
└── .env                           # broker credentials, env vars
```

### 3. Configure

Edit `configs/script-agent-config.yaml`:
- `agent_name` / `display_name`
- `script.component_module` — dotted module path relative to your project root
- `script.component_base_path` — leave as `"."` (resolves to CWD)
- broker connection settings (or set via `.env`)
- schemas and agent card metadata

### 4. Run

```bash
sam run configs/script-agent-config.yaml
```

The `sam` CLI adds CWD to `sys.path`, so `user_scripts.normalize_items` resolves from your project root.

---

## Option B: Kubernetes

### 1. Build the image

```bash
make build IMAGE=registry.example.com/solace/script-item-processor:v1
```

### 2. Push it through your normal registry promotion path

This repo does not assume direct cluster access or internet pulls. In hardened environments, promote the image through your approved registry process first.

### 3. Prepare the SAM config

Start from `examples/script-agent-config.yaml` and change:
- `agent_name`
- `display_name`
- `script.component_module`
- `script.function_name`
- schemas and agent card metadata

The `component_base_path: "."` resolves to the container's WORKDIR (`/app`), where the Dockerfile copies `user_scripts/`.

### 4. Prepare Helm values

Start from `examples/standalone-values.example.yaml` and change:
- `image.repository`
- `image.tag`
- broker values
- persistence secrets
- S3 values

### 5. Deploy with the SAM standalone chart

```bash
helm upgrade -i script-item-processor solace-agent-mesh/sam-agent \
  -n default \
  -f standalone-values.yaml \
  --set-file config.yaml=script-agent-config.yaml
```

### 6. Verify

```bash
kubectl rollout status deployment/script-item-processor -n default
kubectl logs -n default deployment/script-item-processor -c sam --tail=200
```
