FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install Node.js + Claude Code
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash -     && apt-get install -y nodejs     && npm install -g @anthropic-ai/claude-code

WORKDIR /app

# Install Python deps
COPY pyproject.toml .
RUN pip install uv && uv sync --no-dev

COPY src/ src/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "raisebull.main:app", "--host", "0.0.0.0", "--port", "8000"]
