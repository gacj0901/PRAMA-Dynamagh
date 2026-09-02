# Phase 0 architecture

The public API accepts mandates and enqueues work. The worker performs persistent orchestration and talks only to the internal Telegraph Gateway. The gateway alone is permitted to load the EVM private key and complete x402 payment flow. PostgreSQL owns durable state; the existing Redis and RabbitMQ containers are external dependencies accessed over the `firecrawl_backend` network.

