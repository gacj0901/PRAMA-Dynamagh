from app.domain.mandates import ERC8183Job
from app.erc8183.service import DIAMOND, INTENT_ID, INTENT_NAME, PARAMS, ZERO
from app.main import app
from types import SimpleNamespace

from app.workers.tasks import (
    _mark_terminal,
    _record_observation_timeout,
    cancel_erc8183_job,
    cancellation_allowed,
    execute_erc8183_job,
)


class _Query:
    def __init__(self, events): self.events = events
    def filter_by(self, **values): return [event for event in self.events if all(getattr(event, key) == value for key, value in values.items())]


class _Session:
    def __init__(self): self.events = []
    def query(self, _model): return _Query(self.events)
    def add(self, event): self.events.append(event)


def _job():
    return SimpleNamespace(
        erc8183_job_id="job-local", telegraph_job_id="22", state="FUNDED", chain_state="FUNDED",
        failure_code=None, create_tx_hash="0xcreate", approval_tx_hash="0xapprove", deposit_tx_hash="0xdeposit",
        budget_usdc=None, miner_payment_usdc=None, protocol_fee_usdc=None, output_hash=None,
        terminal_tx_hash=None, terminal_block_number=None, terminal_at=None,
    )


CHAIN_TERMINAL = {
    "state": 1, "budget_micro": "1000000", "miner_payment_micro": "980000",
    "protocol_fee_micro": "20000",
    "output_hash": "0x136223bb0e4f476749f055ab8cc9ebd59571f99a6e4c844f8798f8bca07ce11e",
}
TERMINAL_EVENT = {"event": {"tx_hash": "0x0a21681430f2f3c515e2b6cede3ffa39b986ae5481ca74556b0754d4c1e6509b", "block_number": "46293178"}}


def test_g7_model_and_fixture_are_bounded() -> None:
    assert ERC8183Job.__tablename__ == "erc8183_jobs"
    assert any(constraint.name == "uq_erc8183_chain_diamond_job" for constraint in ERC8183Job.__table__.constraints)
    assert DIAMOND == "0x5a2324aA18613FAD4e44bDF0d6c73Ec1f6D87ff8"
    assert INTENT_NAME == "STORM_ALERT"
    assert INTENT_ID == "0x1d7f423dc3020b9066a5a9294633c43a4c619f55349df908009e90488bce085b"
    assert PARAMS == {"addresses": [], "integers": [], "strings": ["24.75", "67.0", "2t", "", ""], "bools": [False]}
    assert ZERO == "0x0000000000000000000000000000000000000000"


def test_g7_routes_and_workers_are_registered_without_invocation() -> None:
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes if hasattr(route, "path")}
    assert ("/v1/erc8183/jobs", ("POST",)) in routes
    assert ("/v1/erc8183/jobs/{erc8183_job_id}", ("GET",)) in routes
    assert ("/v1/erc8183/jobs/{erc8183_job_id}/chain", ("GET",)) in routes
    assert ("/v1/erc8183/jobs/{erc8183_job_id}/cancel", ("POST",)) in routes
    assert execute_erc8183_job.name == "prama.execute_erc8183_job"
    assert cancel_erc8183_job.name == "prama.cancel_erc8183_job"


def test_funded_job_transitions_to_terminal_from_verified_chain_observation() -> None:
    session, job = _Session(), _job()
    _mark_terminal(session, job, CHAIN_TERMINAL, TERMINAL_EVENT)
    assert job.state == job.chain_state == "TERMINAL"
    assert job.failure_code is None
    assert job.output_hash == CHAIN_TERMINAL["output_hash"]
    assert job.terminal_tx_hash == TERMINAL_EVENT["event"]["tx_hash"]
    assert job.terminal_block_number == 46293178
    assert [event.event_type for event in session.events] == ["ERC8183_JOB_TERMINAL"]


def test_observation_timeout_preserves_funded_job_for_late_reconciliation_without_writes() -> None:
    session, job = _Session(), _job()
    _record_observation_timeout(session, job)
    assert job.state == job.chain_state == "FUNDED"
    assert job.failure_code is None
    assert job.create_tx_hash == "0xcreate"
    assert job.approval_tx_hash == "0xapprove"
    assert job.deposit_tx_hash == "0xdeposit"
    assert [event.event_type for event in session.events] == ["ERC8183_JOB_OBSERVATION_TIMEOUT"]

    _mark_terminal(session, job, CHAIN_TERMINAL, TERMINAL_EVENT)
    assert job.telegraph_job_id == "22"
    assert job.state == job.chain_state == "TERMINAL"
    assert job.output_hash == CHAIN_TERMINAL["output_hash"]
    assert [event.event_type for event in session.events] == ["ERC8183_JOB_OBSERVATION_TIMEOUT", "ERC8183_JOB_TERMINAL"]
    assert cancellation_allowed(job) is False
