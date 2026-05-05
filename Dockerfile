ARG BASE_IMAGE=gcr.io/gcp-maas-prod/solace-agent-mesh-enterprise:1.97.2
FROM ${BASE_IMAGE}

USER 0
WORKDIR /tmp/sam-script-agent
COPY pyproject.toml README.md ./
COPY src ./src
RUN chmod -R 755 /tmp/sam-script-agent \
 && python -m pip install --no-cache-dir .

WORKDIR /app
COPY user_scripts ./user_scripts
USER 999
