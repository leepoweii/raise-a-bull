FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install Node.js + Claude Code
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code

WORKDIR /app

RUN pip install uv

COPY pyproject.toml README.md ./
COPY src/ src/
COPY workspace.example/ /app/workspace.example/

RUN uv sync --no-dev

RUN mkdir -p /app/data /app/workspace

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "exec uv run uvicorn raisebull.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
