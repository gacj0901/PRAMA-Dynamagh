# PRAMA-Dynamagh

PRAMA-Dynamagh is the Track 3 structural-evidence layer for Telegraph Protocol.

Phase 0 builds one auditable execution path:

```text
MANDATE -> ACQUISITION -> EVIDENCE -> EVALUATION -> DECISION -> TICKET
```

## Local start

1. Optionally copy `.env.example` to `.env` and supply a dedicated PostgreSQL password (a local-only default is provided for bootstrap).
2. Ensure the existing `firecrawl_backend` Docker network, Redis, and RabbitMQ are running.
3. Run `docker compose up --build`.

The compose project creates only the `postgres`, `api`, `worker`, `gateway`, and `frontend` containers. Redis, RabbitMQ, Firecrawl, and all existing project databases are external dependencies and are never created, changed, or removed here.

Wallet credentials are read by `gateway` only. They are intentionally absent from the API, worker, and frontend service definitions.

The initial container serves a static bootstrap page so G0 can validate infrastructure independently of npm downloads. The React/Vite source is already reserved in `frontend/src`; its execution timeline is introduced with the vertical UI in Commit 06.

## Phase 0 boundaries

ERC-8183 contracts and on-chain anchoring are reserved for later phases. The Phase 0 ticket has `anchor_status: LOCAL_ONLY` and a reproducible Keccak-256 digest.
