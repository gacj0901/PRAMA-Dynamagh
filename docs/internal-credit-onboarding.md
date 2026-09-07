# Email onboarding and internal credit

A person can register with an email and password, receive 0.25 internal credit once, and submit a request without managing a payment wallet. The existing Gateway funds real acquisitions. The public anonymous route remains available with its original G12 limits. The new default frontend shows the account, available credit, requests and results; the existing technical interface is at `/operator`.

## Accounting contract

`UserIdentity` owns one `UserCreditAccount`. PostgreSQL derives balances from `UserCreditLedger`; no mutable balance column exists. All amounts are nonnegative decimals with six fractional places. `WELCOME_CREDIT` increases total/available; `SPEND_RESERVATION` moves available to reserved; `SPEND_SETTLEMENT` moves reserved to spent; `RESERVATION_RELEASE` returns remaining reserved to available. The ledger rejects UPDATE, DELETE and TRUNCATE through database triggers. Insert guards lock the account and reject negative available credit, over-release, oversettlement and cross-user/cross-acquisition lineage. The welcome event has both a deterministic idempotency key and a partial unique index by user.

The authenticated route creates one acquisition, with a budget at most 0.01. For an accepted request, `effective_budget = min(requested, 0.01, user_available, global_available)`. If the requested budget exceeds available credit or the remaining global capacity, admission is rejected (422 or 429); it is not silently reduced to a potentially unusable quote. Requests above 0.01 are rejected. Anonymous fan-out remains at up to five tasks and 0.05 per mandate.

The user-account row is locked before the shared G12 daily ledger. User reservation, USER-origin Mandate, task and the original atomic `_reserve_spend` function commit in one PostgreSQL transaction. The worker verifies both reservations before outbound access. User settlement/release and G12 settlement commit with the completed TelegraphCall. Lost/uncertain external outcomes retain both reservations, including cases where local settlement fails after a response; no zero cost is imputed. A definitely unspent terminal failure releases credit. Task retries reuse the existing durable claim, and settlement keys include mandate/acquisition/type.

`Idempotency-Key` on submission is bound to user and request content. The browser retains the same key after a failed submission until the request text changes or a submission succeeds. A broker error retains the authorized reservation and retrying with that key can safely re-dispatch a queued task. Crash recovery for an external outcome of unknown status remains an explicit operational limitation.

## Identity and sessions

Emails are trimmed and lowercased, unique in PostgreSQL. Passwords use salted PBKDF2-HMAC-SHA256 with 600,000 iterations; see [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). Session tokens contain 256 bits of randomness; only SHA-256 token hashes are persisted. Sessions expire after seven days and logout revokes the session. A repeated registration requires the existing password; it never resets it or grants credit again. The API returns a session token for API clients and sets a Secure, HttpOnly, SameSite=Strict host cookie. The browser uses the cookie and does not save tokens in localStorage. Cookie writes check allowed web origins. Email is an identifier, not verified ownership.

Auth attempts use bounded Redis counters for transport peer and normalized email hash, failing closed on outage. User submission also uses the unchanged public rate limiter. The proxy peer gate is deliberately conservative; it can aggregate users behind the same proxy. Credit per email does not establish unique human identity; multiple registrations remain possible without external email verification. G12 remains the shared financial backstop.

USER-origin artifacts are omitted from anonymous mandate listings and public share/activity surfaces. Direct artifact reads require the owning session, including legacy mandate/ticket paths. Authenticated history and events are scoped to the session user; actor_id is assigned server-side.

## Endpoints

- POST `/v1/users/register` and `/login`: email/password → user and opaque session.
- POST `/v1/users/logout`: revoke the active session.
- GET `/v1/users/status`: module configuration, no account or secret values.
- GET `/v1/users/me/credit` and `/me/credit/events`: derived balance and immutable events.
- POST/GET `/v1/users/me/mandates`: authenticated request and history.
- GET `/v1/users/me/mandates/{id}`: own request results.
- GET `/v1/users/me/history/file`: per-user JSON history export, generated on demand and removed after two hours.

The mandate detail includes acquisition telemetry: requested and resolved
intent, miner/service identity, signal hash, cost, duration, reasoning,
provenance, admissibility and the explicit selection rationale. The rationale
states the evidence boundary accurately: PRAMA-Dynamagh forwards the intent to
Telegraph and records the miner Telegraph returns; it does not invent a local
miner ranking. The user interface renders the state path
`Solicitud → Reserva → Adquisición → Evidencia → Evaluación → Decisión → Respuesta`.

## Deployment

Additive migration `0020_user_credit` follows `0019_shared_policy_gate`. Set API pre-deploy command to `python -m alembic upgrade head`; deploy API and worker from the same commit before enabling `USER_ONBOARDING_ENABLED=true`. `WELCOME_CREDIT_USDC` defaults to 0.05 internally, displayed as 5 credits (1 credit = 0.01 internal USDC); changing it affects only future identities, not existing grants. `USER_WEB_ORIGINS` lists exact allowed browser origins, defaulting to the production frontend. Cookies require HTTPS. Disabling new registrations/submissions does not disable settlement of already reserved user mandates. Roll back by disabling the module and restoring the matching UI; do not destroy or downgrade its ledger. No Gateway variable or payment code changes are needed.

## Out of scope

No per-user wallets, user private-key custody, faucets, user deposits, OAuth/provider, external email verification, password recovery or CD/CDG enforcement. CD/CDG remain descriptive shadow checkpoints. No change to the existing raw-upstream normalization finding, typed E1 boundary or test-network payment rail. A test-network payment is not represented as mainnet settlement.

Validation and live production receipts are reported separately; local concurrency and mutation tests are never labeled production execution.
