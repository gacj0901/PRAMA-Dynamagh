import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.domain.mandates import ERC8183Job, Evidence
from app.erc8183.evidence import VERSION

LIVE_JOB = "04e5ba3c-d4e2-45d1-a21e-cf10f510916c"


@pytest.fixture
def session():
    value = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]))()
    try:
        yield value
    finally:
        value.rollback()
        value.close()


def candidate(job_id: str) -> Evidence:
    return Evidence(
        evidence_id=str(uuid.uuid4()), mandate_id="g9-dry-run", acquisition_id=None,
        telegraph_call_id=None, erc8183_job_id=job_id, evidence_type="TELEGRAPH_ERC8183_RESULT",
        source_kind="TELEGRAPH_ERC8183", source_intent="STORM_ALERT", source_miner_id=None,
        source_signal_hash=None, normalized_payload={"schema": "test"},
        content_hash="0x" + "12" * 32, normalizer_version=VERSION,
        provenance_status="VERIFIED", admissibility="ADMITTED", limitation_codes=[],
    )


def test_erc8183_evidence_uniqueness_rolls_back_cleanly(session):
    job = session.get(ERC8183Job, LIVE_JOB)
    assert job is not None
    before = session.query(Evidence).filter_by(erc8183_job_id=LIVE_JOB, normalizer_version=VERSION).count()
    session.add(candidate(LIVE_JOB))
    with pytest.raises(IntegrityError) as raised:
        session.flush()
    assert getattr(getattr(raised.value, "orig", None), "diag", None).constraint_name == "uq_evidence_erc8183_job_normalizer"
    session.rollback()
    assert session.query(Evidence).filter_by(erc8183_job_id=LIVE_JOB, normalizer_version=VERSION).count() == before
