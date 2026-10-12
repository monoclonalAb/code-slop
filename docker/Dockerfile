# Agent + evaluation image. Python 3.12 (matches SlopCodeBench's docker-python3.12-uv env),
# uv for evaluation, Node 24 + pi for the agent.
FROM node:24-trixie-slim AS node

FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ripgrep ca-certificates procps less \
 && rm -rf /var/lib/apt/lists/*

ARG PI_VERSION=1.0.4
RUN npm install -g --no-fund --no-audit @earendil-works/pi-coding-agent@${PI_VERSION} \
 && pi --version

# Runs as the host uid via `docker run --user`; give it a writable HOME.
RUN mkdir -p /home/agent /workspace && chmod 777 /home/agent /workspace
ENV HOME=/home/agent \
    PI_CODING_AGENT_DIR=/pi-agent \
    UV_CACHE_DIR=/cache/uv \
    PIP_CACHE_DIR=/cache/pip \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
