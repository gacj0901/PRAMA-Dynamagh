import os
import re

from sqlalchemy.orm import Session

from app.domain.mandates import ERC8183Job, UsageEvent

CHAIN_ID = 84532
DIAMOND = "0x5a2324aA18613FAD4e44bDF0d6c73Ec1f6D87ff8"
INTENT_NAME = "STORM_ALERT"
INTENT_ID = "0x1d7f423dc3020b9066a5a9294633c43a4c619f55349df908009e90488bce085b"
ZERO = "0x0000000000000000000000000000000000000000"
PARAMS = {"addresses": [], "integers": [], "strings": ["24.75", "67.0", "2t", "", ""], "bools": [False]}


def configured_callback() -> str:
    value = os.environ.get("ERC8183_CALLBACK_ADDRESS", ZERO)
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
        raise ValueError("ERC8183_CALLBACK_INVALID")
    return value.lower()


def request_fixture(session: Session) -> tuple[ERC8183Job, str]:
    callback = configured_callback()
    existing = session.query(ERC8183Job).filter(
        ERC8183Job.chain_id == CHAIN_ID,
        ERC8183Job.diamond_address == DIAMOND.lower(),
        ERC8183Job.intent_id == INTENT_ID,
        ERC8183Job.callback_address == callback,
        ERC8183Job.state.in_(["PREPARING", "ESCROW_READY", "SUBMITTED", "FUNDED", "TERMINAL", "CANCEL_PENDING"]),
    ).order_by(ERC8183Job.created_at.desc()).first()
    if existing:
        return existing, "ALREADY_TERMINAL" if existing.state == "TERMINAL" else "ALREADY_SUBMITTED"
    job = ERC8183Job(chain_id=CHAIN_ID, diamond_address=DIAMOND.lower(), intent_name=INTENT_NAME, intent_id=INTENT_ID, callback_address=callback, params_payload=PARAMS, state="PREPARING")
    session.add_all([job, UsageEvent(mandate_id=None, event_type="ERC8183_JOB_REQUESTED", metadata_={"intent": INTENT_NAME})])
    session.flush()
    return job, "PREPARING"
