# Deployment

## 1. Build the image

```bash
make build IMAGE=registry.example.com/solace/script-item-processor:v1
```

## 2. Push it through your normal registry promotion path

This repo does not assume direct cluster access or internet pulls. In hardened environments, promote the image through your approved registry process first.

## 3. Prepare the SAM config

Start from `examples/script-agent-config.yaml` and change:
- `agent_name`
- `display_name`
- `script.component_module`
- `script.function_name`
- schemas and agent card metadata

## 4. Prepare Helm values

Start from `examples/standalone-values.example.yaml` and change:
- `image.repository`
- `image.tag`
- broker values
- persistence secrets
- S3 values

## 5. Deploy with the SAM standalone chart

```bash
helm upgrade -i script-item-processor solace-agent-mesh/sam-agent \
  -n default \
  -f standalone-values.yaml \
  --set-file config.yaml=script-agent-config.yaml
```

## 6. Verify

```bash
kubectl rollout status deployment/script-item-processor -n default
kubectl logs -n default deployment/script-item-processor -c sam --tail=200
```
