# raise-a-bull Dockerfile — OpenClaw runtime only, no content baked in
FROM node:20-slim

ARG OPENCLAW_VERSION=latest
RUN npm install -g openclaw@${OPENCLAW_VERSION}

ARG GOG_VERSION=0.12.0
RUN npm install -g @nicepkg/gog@${GOG_VERSION} || true

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
EXPOSE 18888

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:18888/health || exit 1

CMD ["openclaw", "gateway", "--workspace", "/app/workspace", "--port", "18888"]
