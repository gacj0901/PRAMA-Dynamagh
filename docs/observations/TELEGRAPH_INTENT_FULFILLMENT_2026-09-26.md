# Telegraph intent and delivery observations — 2026-09-26

Source: operator-provided real execution records and report of Telegraph team
feedback. These are documentary observations, not a new semantic evaluator or
permanent protocol axiom. No Evidence, Decision or Ticket was retroactively changed.

ACQUISITION_SUCCESS != EVIDENCE_ADMISSIBLE != RESULT_DELIVERED != SEMANTIC_TASK_FULFILLED.

* Transport/acquisition success: a selected provider returned a technically successful response.
* Evidence admissibility: provenance and admissibility checks accepted the evidence.
* Delivery: admitted Consumer Result content was made available/returned through the result surface.
* Semantic fulfillment: whether that content actually satisfies the higher-level task.

Semantic task fulfillment is not currently inferred from delivery. No semantic
fulfillment counter exists. The persisted `M2M_CONSUMER_RESULT_DELIVERED` event
retains its existing server-delivery meaning. Public metric key is now
`consumer_results_delivered` (previous key removed); it still deduplicates by
mandate and counts delivery, not polling or semantic success.

## Current intent observations

WEB_SEARCH is currently understood as a search/retrieval primitive. A valid
delivery can be insufficient for multi-source research and synthesis. Telegraph
team clarified this distinction in the operator's reported Discord exchange.

RESEARCH_QUERY: the latest reported real acquisition failed with
`TELEGRAPH_REQUEST_FAILED`. `TELEGRAPH_STATUS = TEAM_ACKNOWLEDGED / UNDER_INVESTIGATION`.
This is not a confirmed Telegraph bug. No guessed replacement or new canonical
intent has been introduced; routing and PRAMAgraph semantics are unchanged.

## Execution A — WEB_SEARCH

| Field | Recorded value |
|---|---|
| origin | M2M |
| mandate_id | 742b0c6a-e962-43b5-99d6-74d45bc8cb70 |
| acquisition_id | 600f2041-6832-483f-91dc-e23a0ce03b2d |
| requested_intent | WEB_SEARCH |
| evidence_id | d68c9098-cd2b-42ce-bd59-9551731a19d5 |
| evidence_content_hash | 0x1cad4c632f374dfd6a82ef513234767478f3f353f7d566d49667fc820f74244e |
| acquisition | SUCCEEDED |
| evidence | ADMITTED |
| provenance | VERIFIED |
| structural_state | STRUCTURALLY_ADMISSIBLE |
| decision | PERMIT |
| consumer_result | DELIVERED |
| ticket_id | d743c4c2-b763-4bbe-ba54-dacaa51dc14e |
| ticket_hash | 0x0fb5f8d9070a399065c266b60e4551f24ecfafbecd9c982ad72d458b6b3c3cb8 |
| ticket_hash_algorithm | keccak256 |
| anchor_status | LOCAL_ONLY |
| semantic_task_fulfillment | NOT_ESTABLISHED |

Reason: the returned result was metadata for a Google Search URL, rather than
the substantive multi-source research requested. This annotation is documentary.
It does not invalidate or mutate the recorded governance outcome.

## Execution B — RESEARCH_QUERY

| Field | Recorded value |
|---|---|
| origin | M2M |
| mandate_id | 194f18e3-7a59-4490-a1fc-7a49d6a3dad8 |
| acquisition_id | c955ef96-b25f-46d9-ae03-b2ce87c1280a |
| requested_intent | RESEARCH_QUERY |
| acquisition | FAILED |
| failure_code | TELEGRAPH_REQUEST_FAILED |
| evidence | NONE |
| structural_state | STRUCTURALLY_BLOCKED |
| limitation | REQUIRED_ACQUISITION_FAILED |
| decision | BLOCK |
| reason | REQUIRED_EVIDENCE_REJECTED |
| consumer_result | NOT_AVAILABLE |
| ticket_id | 0ee95fa5-1a51-47c8-a40e-289a689bb01b |
| ticket_hash | 0x232e61304139b57f7ad5e2e6303b9a18d79a426753827cd53893e273d8016a7c |

## Engagement attribution

Telegraph Discord: Track 3 real paid M2M field report, PUBLISHED; outcome
ACKNOWLEDGED, according to the operator. Public message URL: NOT_RECORDED.
The response clarified technical delivery versus semantic fulfillment and
WEB_SEARCH retrieval semantics. Follow-up: RESEARCH_QUERY under investigation.
This is ENGAGEMENT / TECHNICAL FEEDBACK, not an additional agent, wallet or
M2M adoption count. This task sent no Discord message and made no paid request.
