# Consolidated local implementation and publication status

The canonical repository is `PRAMA-Dynamagh`, branch `main`.
Track 3, internal-credit onboarding and the previously uncommitted authority
composition work are integrated there. The pending original work was preserved
in commit `cd3a3d1` before resolving the merge.

Integrated history:

- `93122c2`, `480099b`, `60b5f83`: bounded execution, fan-out and descriptive authority checkpoints.
- `06994ee`, `bed5115`: internal credit, email/password sessions, ownership, migration and user interface.
- The authority composition now runs beside those checkpoints in the current acquisition worker. Canonical O_AGENT ordering and run lineage are preserved. Neither composed restrictions nor checkpoint failures enforce a new payment decision.
- Both `AUTHORITY_CHECKPOINT` and `AUTHORITY_COMPOSITION` are supported in the shared append-only substrate. Frozen E3/G13, KernelV3, Gateway and existing G12 code remain unchanged by this consolidation.
- The alternative README was consolidated into the canonical README, retaining the original in Git history and correcting unsupported production claims.

Validation from the canonical checkout:

- Fresh local PostgreSQL migration to `0020_user_credit` succeeded.
- Backend unit/integration suite: 245 passed.
- Frontend: typecheck, 4 tests and production build passed.
- Full authority PostgreSQL validator: PASS, including 34 schema objects, 22 targeted authority tests, integration suite and complete backend regression.
- The local PostgreSQL validator now recognizes the user tables, balance view and current migration; accepts the SQLAlchemy psycopg URL; and returns a failing exit code when validation fails.

Publication remains separate from local validation. The user will perform the
GitHub push. No push, PR, production deployment or paid acquisition was performed
as part of consolidation. Production onboarding and a paid user mandate remain
**NOT_VERIFIED**. The last observed production code was `60b5f83`, with
`USER_ONBOARDING_ENABLED=false`; that deployment has not been rechecked here.

After publishing, deployment must apply `0020_user_credit` to the intended
environment before enabling onboarding. Production registration, credit and
one bounded user acquisition still require operational verification.

See [the onboarding contract](internal-credit-onboarding.md) and
[authority semantics](authority-runtime-shadow.md).
