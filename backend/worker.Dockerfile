FROM node:22.14.0-bookworm-slim AS telegraph-mcp-runtime

WORKDIR /opt/telegraph-mcp
COPY mcp-runtime/package.json ./package.json
COPY mcp-runtime/package-lock.json ./package-lock.json
RUN npm ci --omit=dev --ignore-scripts \
    && test -x node_modules/.bin/telegraph-protocol-mcp

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY --from=telegraph-mcp-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=telegraph-mcp-runtime /opt/telegraph-mcp /opt/telegraph-mcp
RUN ln -s /opt/telegraph-mcp/node_modules/.bin/telegraph-protocol-mcp /usr/local/bin/telegraph-protocol-mcp \
    && node --version \
    && test -x /usr/local/bin/telegraph-protocol-mcp

ENV TELEGRAPH_MCP_COMMAND=/usr/local/bin/telegraph-protocol-mcp

COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[test]"
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY tests ./tests

# A dedicated, private worker process: no API server or process supervisor.
CMD ["celery", "--app", "app.workers.celery_app", "worker", "--beat", "--loglevel=INFO"]
