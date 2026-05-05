IMAGE ?= docker.io/library/sam-script-agent:local-v1
BASE_IMAGE ?= gcr.io/gcp-maas-prod/solace-agent-mesh-enterprise:1.97.2

.PHONY: build validate

build:
	docker build --build-arg BASE_IMAGE=$(BASE_IMAGE) -t $(IMAGE) .

validate:
	python3 -m py_compile src/sam_script_agent/*.py src/sam_script_agent/example_scripts/*.py user_scripts/*.py
