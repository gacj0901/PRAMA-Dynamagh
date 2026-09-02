from app.domain.mandates import AnchorAttempt, Ticket
from app.main import app
from app.workers.tasks import execute_ticket_anchor


def test_anchor_persistence_metadata_is_explicit() -> None:
    assert AnchorAttempt.__tablename__ == "anchor_attempts"
    assert AnchorAttempt.__table__.c.ticket_id.unique is None
    assert any(constraint.name == "uq_anchor_attempt_ticket" for constraint in AnchorAttempt.__table__.constraints)
    assert {"block_hash", "chain_id", "contract_address", "tx_hash"}.issubset(Ticket.__table__.c.keys())


def test_anchor_routes_and_worker_are_registered_without_invocation() -> None:
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes if hasattr(route, "path")}
    assert ("/v1/tickets/{ticket_id}/anchor", ("POST",)) in routes
    assert ("/v1/tickets/{ticket_id}/anchor", ("GET",)) in routes
    assert execute_ticket_anchor.name == "prama.execute_ticket_anchor"
