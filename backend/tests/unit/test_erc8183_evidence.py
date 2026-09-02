from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.erc8183.evidence import (
    DIAMOND,
    RECEIVER,
    VERSION,
    SourceValidationError,
    dry_run,
    promote_verified_erc8183_job,
    promotion_status,
    reconstruct,
)


OUTPUT = "0x136223bb0e4f476749f055ab8cc9ebd59571f99a6e4c844f8798f8bca07ce11e"
CALLBACK = "0x69d05c65260ff23f474f6f37018ce16c6708ddeceb913d4ee64f8500fe650b31"
CREATE = "0x26faea5747e0e3fdfdcc95fcbcc8e5abb4ca4590955caf9835305f4adf0980a5"
TERMINAL = "0x83b38989077875b4a69f60c2f601751f5f9e7a384ecc980296a4d6838934a030"
INTENT = "0x1d7f423dc3020b9066a5a9294633c43a4c619f55349df908009e90488bce085b"


def job():
    return SimpleNamespace(
        erc8183_job_id="local-27", state="TERMINAL", telegraph_job_id="27", chain_id=84532,
        diamond_address=DIAMOND, callback_address=RECEIVER, callback_verified=True,
        output_hash=OUTPUT, callback_response_hash=CALLBACK, terminal_tx_hash=TERMINAL,
        terminal_block_number=46306768, create_tx_hash=CREATE, create_block_number=46306628,
        intent_name="STORM_ALERT", intent_id=INTENT,
    )


def reader(overrides=None):
    overrides = overrides or {}
    response = {"addresses": ["0x00000000000000000000000000000000000000AB"], "integers": [9007199254740993, "000980000"], "strings": ["24.75", "exact"], "bools": [True, False]}
    values = {
        "job": {"state": 1, "output_hash": OUTPUT, "callback": RECEIVER},
        "terminal": {"event": {"tx_hash": TERMINAL, "block_number": "46306768"}},
        "verify": {"status": "VALID", "receiver_code_present": True, "receiver_diamond": DIAMOND, "stored_response_hash": CALLBACK, "expected_response_hash": CALLBACK, "response": response},
    }
    values.update(overrides)
    def read(path):
        if "/terminal?" in path: return values["terminal"]
        if "/subnet-receiver/verify?" in path: return values["verify"]
        return values["job"]
    return read


def test_reconstructs_canonical_erc8183_evidence_and_keeps_hashes_distinct():
    candidate = reconstruct(job(), reader())
    core = candidate.core
    assert candidate.validation == "VERIFIED"
    assert core["schema"] == "prama.evidence.erc8183.v0"
    assert core["response"]["addresses"] == ["0x00000000000000000000000000000000000000ab"]
    assert core["response"]["integers"] == ["9007199254740993", "980000"]
    assert core["telegraph_output_hash"] == OUTPUT
    assert core["callback_response_hash"] == CALLBACK
    assert "created_at" not in core and "evidence_id" not in core
    result = dry_run(job(), reader())
    assert result["content_hash"] not in {OUTPUT, CALLBACK}
    assert result["evidence_set_hash"] not in {OUTPUT, CALLBACK, result["content_hash"]}
    assert result["ticket_hash"] not in {OUTPUT, CALLBACK, result["content_hash"], result["evidence_set_hash"]}


def test_dry_run_is_repeatable_without_uuid_or_timestamp_entropy():
    first, second = dry_run(job(), reader()), dry_run(job(), reader())
    for key in ("evidence_core", "content_hash", "evidence_set_hash", "structural_state", "decision_state", "reason_codes", "ticket_core", "ticket_hash"):
        assert first[key] == second[key]
    assert first["structural_state"] == "STRUCTURALLY_ADMISSIBLE"
    assert first["decision_state"] == "PERMIT"
    assert first["reason_codes"] == ["ALL_REQUIRED_EVIDENCE_ADMITTED"]


@pytest.mark.parametrize(("mutate", "overrides", "code"), [
    (lambda value: setattr(value, "state", "FUNDED"), {}, "JOB_NOT_TERMINAL"),
    (lambda value: setattr(value, "output_hash", "0x" + "00" * 32), {}, "OUTPUT_HASH_ZERO"),
    (lambda value: setattr(value, "callback_verified", False), {}, "CALLBACK_UNVERIFIED"),
    (lambda value: setattr(value, "callback_response_hash", "0x" + "00" * 32), {}, "CALLBACK_HASH_ZERO"),
    (lambda value: value, {"verify": {"status": "VALID", "receiver_code_present": True, "receiver_diamond": DIAMOND, "stored_response_hash": CALLBACK, "expected_response_hash": "0x" + "33" * 32, "response": {"addresses": [], "integers": [], "strings": [], "bools": []}}}, "CALLBACK_HASH_MISMATCH"),
    (lambda value: value, {"verify": {"status": "VALID", "receiver_code_present": True, "receiver_diamond": "0x0000000000000000000000000000000000000001", "stored_response_hash": CALLBACK, "expected_response_hash": CALLBACK, "response": {"addresses": [], "integers": [], "strings": [], "bools": []}}}, "RECEIVER_DIAMOND_MISMATCH"),
    (lambda value: value, {"terminal": {"event": {"tx_hash": "0x" + "44" * 32, "block_number": "46306768"}}}, "TERMINAL_TX_MISMATCH"),
    (lambda value: setattr(value, "chain_id", 1), {}, "CHAIN_ID_MISMATCH"),
])
def test_source_guard_fails_closed(mutate, overrides, code):
    value = deepcopy(job())
    mutate(value)
    with pytest.raises(SourceValidationError, match=code):
        reconstruct(value, reader(overrides))


def test_promotion_status_is_idempotent_and_accepts_only_a_persisted_local_id():
    source = job()
    class Query:
        def __init__(self, existing): self.existing = existing
        def filter_by(self, **_values): return self
        def one_or_none(self): return self.existing
    class Session:
        def __init__(self, existing): self.existing = existing
        def get(self, _model, local_id): return source if local_id == source.erc8183_job_id else None
        def query(self, _model): return Query(self.existing)
    assert promotion_status(Session(None), "local-27") == "READY_TO_PROMOTE"
    assert promotion_status(Session(SimpleNamespace()), "local-27") == "ALREADY_PROMOTED"
    assert promotion_status(Session(None), "arbitrary-payload-is-not-an-id") == "ERC8183_JOB_MISSING"
    assert VERSION == "telegraph-erc8183-evidence-v0"

    preview = promote_verified_erc8183_job(Session(None), "local-27", reader())
    assert preview["status"] == "DRY_RUN"
    assert preview["purpose"].startswith("Evaluate certified Telegraph ERC-8183 Job 27")
