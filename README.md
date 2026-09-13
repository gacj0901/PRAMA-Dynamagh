# PRAMA-Dynamagh
Structural Layer of Knowledge Viability

PRAMA-Dynamagh is an acquisition and decision layer for autonomous agents. It turns an authorized mandate into a Telegraph request, preserves the complete evidence lineage, evaluates the result, and issues a replayable decision before the next action is allowed.

## Core workflow

```
Mandate
  → Authority (G12 + G13)
  → AcquisitionTask
  → Private Gateway
  → Telegraph / x402
  → Miner / Signal
  → Evidence
  → PRAMAgraph / Evaluation
  → Decision
  → Ticket
  → O_AGENT observation and longitudinal reevaluation
```

The scheduler follows a strict sequence:

```
scheduler tick
  → previously authorized work?
  → cadence due?
  → G13 trajectory authority
  → G12 economic authority
  → execute the next authorized action
```

If there is no authorized work, the scheduler remains idle. A restrictive authority result is never bypassed by a positive result from another gate.

## What the system does

- Acquires Telegraph intelligence through a private Gateway and x402 payment flow.
- Represents work as durable `Mandate`, `AcquisitionTask`, and `TelegraphCall` records.
- Stores raw responses as attributable `Evidence` and evaluates them through PRAMAgraph.
- Produces deterministic `Decision` and `Ticket` records for downstream execution.
- Preserves lineage, canonical hashes, policy versions, and replay information.
- Attributes every action to an `AgentIdentity` and records longitudinal observations through `O_AGENT`.
- Supports multiple intents and controlled fan-out under the active authority profile.
- Provides bounded, single-use recovery for a G13 review caused only by a missing critical observation.

## Component responsibilities

### Frontend

The frontend provides the operator console, workflow submission, lineage views, autonomy status, and public activity views. It does not hold payment credentials or decide whether an action is authorized.

### API

The API validates requests, creates mandates and tasks, exposes read models, and coordinates persistence. It is the control-plane boundary for clients and operators.

### Scheduler and worker

The scheduler selects work that is already authorized and due. The worker executes the selected task, records each transition, and stops when an authority or payment guard denies the action.

### Authority layer

- **G12** is the independent economic authority. It enforces budgets, reservations, settlement accounting, and double-payment protection.
- **G13** is the independent longitudinal authority. It evaluates observations, recurrence, failures, missing data, and recovery state.
- **`authority_mode`** determines whether the composed result is binding. In binding mode, execution requires every required guard to permit it.

### Gateway

The Gateway is the private boundary to Telegraph. It owns the x402 signer, performs provider communication and payment verification/settlement, and returns a normalized, auditable result to the API and worker.

### Evidence, evaluation, and tickets

The pipeline keeps the raw provider response, its provenance, the structural evaluation, the resulting decision, and the final ticket linked by immutable identifiers and hashes. Historical evaluations can be replayed with the policy version that produced them.

### O_AGENT and AgentIdentity

`AgentIdentity` identifies the acting autonomous principal. `O_AGENT` records observations about execution outcomes and trajectory so that G13 can reason over ordered history rather than isolated requests.

## System architecture

```text
Frontend → API → PostgreSQL
              ├→ Redis / RabbitMQ → Worker
              └→ Private Gateway → Telegraph / x402
```

Repository areas:

- `frontend/`: operator console and public activity views.
- `backend/`: API, scheduler, worker, authority, persistence, and Alembic migrations.
- `gateway/`: Telegraph integration and x402 payment boundary.
- `contracts/`: ERC-8183 and Base Sepolia integration artifacts.
- `docs/`: architecture, authority, identity, autonomy, and workflow documentation.

## Safety and accounting invariants

- Payment state is reconciled before an ambiguous retry.
- A settled payment cannot be charged again for the same acquisition.
- External provider failures remain observable and attributable; they do not silently rewrite G13 history.
- Recovery authorizations are append-only, single-use, bounded, and observable by `O_AGENT`.
- Signer credentials remain in the Gateway and are never exposed to the frontend.
- Authority, payment, idempotency, and concurrency guards are evaluated before external execution.

## Telegraph, x402, and on-chain integration

The repository contains the Telegraph/x402 acquisition path and integration artifacts for ERC-8183 and Base Sepolia. On-chain anchoring is an additional capability controlled by deployment configuration; the core acquisition, evidence, evaluation, and ticket pipeline remains structurally traceable without assuming that every deployment enables writes.

## Local development

Requirements: Docker Compose, Python 3.11+, Node.js 20+, and the variables described in `.env.example`.

```
docker compose up --build
```

Backend tests:

```
cd backend
python -m pytest -q
```

The API health endpoint and the documentation under `docs/` describe the available local services and read models.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/FULL_AUTONOMY.md`](docs/FULL_AUTONOMY.md)
- [`docs/G13_O_AGENT.md`](docs/G13_O_AGENT.md)
- [`docs/G13_AGENT_IDENTITY.md`](docs/G13_AGENT_IDENTITY.md)
- [`docs/competition-workflows.md`](docs/competition-workflows.md)

Operational checks, deployment observations, and runtime evidence are kept separately in the [production log](docs/PRODUCTION-LOG.md).
