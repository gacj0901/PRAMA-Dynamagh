# Authority runtime shadow checkpoint

The autonomous worker reaches `PRE_NEXT_ACTION_AUTHORITY_CHECK` after the
existing G12 reservation has been durably verified and immediately before the
Gateway request.

The checkpoint evaluates the independent CD (E3-A), G12 reservation
eligibility, and CDG (G13-D) authorities conjunctively. It uses the existing
O_AGENT read-only stream and the append-only `policy_evaluations` substrate.
The composition is persisted as `AUTHORITY_COMPOSITION` with canonical input
and result hashes, applicability, rule attribution, replay identity, and
shadow divergence.

This release is shadow-only: the worker does not use the composed result to
halt, throttle, review, or otherwise change the existing execution path.
Gamma coordinates are not authority inputs. Missing epistemic input is recorded
explicitly and remains fail-closed in the would-be composition.
