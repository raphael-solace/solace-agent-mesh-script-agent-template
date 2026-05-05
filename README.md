# Solace Agent Mesh Script Agent Template

A minimal template for **pure-Python agents** in Solace Agent Mesh that execute scripts directly instead of using an LLM-backed `SamAgentApp`.

## What this solves

Stock SAM workflows can run without a model, but normal SAM agents currently require one. This template provides a custom app module and component that:

- publishes a normal SAM/A2A agent card
- listens on the standard agent request topic
- executes Python directly
- returns deterministic results
- supports workflow structured invocation and artifact output
- works for direct chat-style requests as well

This is useful for:

- validators
- normalizers
- deterministic data transforms
- rule engines
- light orchestration helpers
- bank / air-gapped / no-LLM environments

## Repo layout

- `src/sam_script_agent/`: reusable runtime package
- `user_scripts/`: customer-owned script functions
- `examples/script-agent-config.yaml`: standalone script-agent config
- `examples/standalone-values.example.yaml`: example Helm values for `sam-agent`
- `examples/workflow-config.yaml`: example workflow calling the script agent
- `docs/DEPLOYMENT.md`: deployment steps

## Script contract

The easiest shape is:

```python
async def run(input_data: dict, context=None) -> dict:
    ...
```

It also supports kwargs-style scripts such as:

```python
async def run(items=None, item=None, text=None, operation="normalize", context=None, **kwargs):
    ...
```

## Chat behavior

For direct chat calls, the runtime renders the **actual result payload** as the visible text response. That means users see JSON output instead of a summary string.

Example prompts that the sample script supports:

```text
["  valve  ","pump", "", " filter "]
```

```text
uppercase
espresso valve
```

```text
Give me the length of: grinder motor
```

## Build

```bash
make build IMAGE=docker.io/library/script-item-processor:local-v1
```

## Validate

```bash
make validate
```

## Deploy

Use the files in `examples/` together with the `solace-agent-mesh/sam-agent` chart. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Notes

- The runtime is generic; customers mainly edit `user_scripts/` and the example config.
- In enterprise environments, image build and promotion should go through the standard approval layer before Helm deployment.
- The sample workflow shows how to call a script-backed agent from a SAM workflow without introducing an LLM.
