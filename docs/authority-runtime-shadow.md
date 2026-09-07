# Authority runtime checkpoint

The autonomous worker reaches `PRE_NEXT_ACTION_AUTHORITY_CHECK` after the
existing G12 reservation has been durably verified and immediately before the
Gateway request.

The checkpoint evaluates the independent CD (E3-A), G12 reservation
eligibility, and CDG (G13-D) authorities conjunctively. It uses the existing
O_AGENT read-only stream and the append-only `policy_evaluations` substrate.
The composition is persisted as `AUTHORITY_COMPOSITION` with canonical input
and result hashes, applicability, rule attribution, replay identity, and
shadow divergence.

The autonomous worker now consumes the composed result as binding authority.
`CONTINUE` issues a one-shot `ExecutionPermit`; `THROTTLE` requires its
configured constraint; `REVIEW` and `HALT` stop before network I/O and payment.
The diagnostic observer path remains available with `shadow_mode=true` for
non-autonomous reporting.
Gamma coordinates are not authority inputs. Missing epistemic input before the
first evidence acquisition is recorded explicitly as `NOT_APPLICABLE`; the
binding decision still requires valid G12 and G13 authority.

The boundary is implemented in `app/workers/acquisition.py`, after the durable
request and verified G12 reservation. `app/workers/tasks.py` retains the current
queued-task wrapper and payment claim behavior. The descriptive Track 3
checkpoints remain independent from `AUTHORITY_COMPOSITION`.

Composition receives the complete canonical O_AGENT sequence for the identity,
including prior runs and the current run. Each checkpoint owns its transaction.
A binding restriction is recorded and leaves `network_attempted=false`; the
existing diagnostic observer can still produce `UNAVAILABLE` records when its
own persistence path is unavailable.
