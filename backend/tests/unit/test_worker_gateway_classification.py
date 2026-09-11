"""Worker failure classification: transport vs semantic Gateway responses.

The production incident behind these tests: every ``HTTPError`` from the
Gateway was flattened to ``GATEWAY_UNAVAILABLE`` because ``HTTPError`` has no
``detail`` attribute and its ``str()`` never matched the known-code list.  The
Gateway's JSON body (carrying the real code) was discarded unread, so an
upstream declaration such as ``PAYMENT_FAILED`` was indistinguishable from the
Gateway being down.

These tests exercise ``execute_one`` through a stubbed ``urlopen`` so no real
network, payment, or Telegraph traffic occurs.
"""
import io
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from app.workers import acquisition


class _UnclosableSession:
    """Swallow close() so the ``finally`` block cannot tear down the stub."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        return None


def _fake_session():
    """Minimal stand-in covering the single happy-path query touchpoint."""
    mandate = SimpleNamespace(
        mandate_id="mandate-" + uuid.uuid4().hex,
        origin="USER",
        max_budget_usdc="0.010000",
        status="ACQUIRING",
    )
    task = SimpleNamespace(
        acquisition_id="acq-" + uuid.uuid4().hex,
        mandate_id=mandate.mandate_id,
        status="QUEUED",
        attempt_count=0,
        started_at=None,
        completed_at=None,
        failure_code=None,
        query="synthetic operator question",
        requested_intent=None,
    )
    added = []

    return mandate, task, added


@pytest.fixture
def run_once(monkeypatch):
    mandate, task, added = _fake_session()

    class _Query:
        def __init__(self, result):
            self._result = result

        def filter_by(self, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def with_for_update(self):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return list(self._result) if isinstance(self._result, (list, tuple)) else [self._result]

        def one(self):
            if self._result is None:
                raise LookupError("unexpected empty query")
            return self._result

        def one_or_none(self):
            return self._result

        def count(self):
            return len(self.all())

    tasks_list = [task]

    def query(model, *a, **k):
        if model is acquisition.Mandate:
            return _Query(mandate)
        if model is acquisition.AcquisitionTask:
            return _Query(tasks_list)
        return _Query(None)

    session = _UnclosableSession(SimpleNamespace(
        query=query,
        get=lambda model, key: task if model is acquisition.AcquisitionTask else None,
        rollback=lambda: None,
        commit=lambda: None,
        add=added.append,
    ))
    monkeypatch.setattr(acquisition, "SessionLocal", lambda: session)
    monkeypatch.setenv("GATEWAY_URL", "http://gateway.test")
    # External collaborators on the success/validation path:
    reservation = SimpleNamespace(reserved_usdc=Decimal("0.010000"))
    monkeypatch.setattr(acquisition, "verify_spend_reservation", lambda *a, **k: reservation)
    monkeypatch.setattr(acquisition, "uncertain_hold", lambda *a, **k: Decimal("0"))
    monkeypatch.setattr(acquisition.user_credit, "verify_reserved", lambda *a, **k: None)
    monkeypatch.setattr(acquisition, "transition_mandate", lambda *a, **k: None)

    def run(gateway_behavior):
        def fake_urlopen(request, **kwargs):
            assert kwargs.get("timeout") == acquisition.GATEWAY_REQUEST_TIMEOUT_SECONDS
            return gateway_behavior(request)

        monkeypatch.setattr(acquisition, "urlopen", fake_urlopen)
        return acquisition.execute_one(mandate.mandate_id, task.acquisition_id), task, added

    return run


def _http_error(code: int, body: dict) -> HTTPError:
    return HTTPError(
        url="http://gateway.test/ask",
        code=code,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(json.dumps(body).encode()),
    )


def test_gateway_semantic_payment_failed_is_preserved(run_once):
    code, task, added = run_once(lambda request: (_ for _ in ()).throw(_http_error(400, {"code": "PAYMENT_FAILED"})))
    assert code == "PAYMENT_FAILED"
    assert task.failure_code == "PAYMENT_FAILED"
    uncertainty = [e for e in added if getattr(e, "event_type", None) == "ACQUISITION_PAYMENT_UNCERTAIN"]
    assert uncertainty, "gateway answered => outcome is payment-uncertain, not clean"


def test_gateway_payment_required_is_preserved(run_once):
    code, task, added = run_once(lambda request: (_ for _ in ()).throw(_http_error(402, {"code": "PAYMENT_REQUIRED"})))
    assert code == "PAYMENT_REQUIRED"
    assert task.failure_code == "PAYMENT_REQUIRED"


def test_transport_failure_stays_gateway_unavailable(run_once):
    def refuse(request):
        raise URLError(ConnectionRefusedError("connection refused"))

    code, task, added = run_once(refuse)
    assert code == "GATEWAY_UNAVAILABLE"
    assert task.failure_code == "GATEWAY_UNAVAILABLE"
    uncertainty = [e for e in added if getattr(e, "event_type", None) == "ACQUISITION_PAYMENT_UNCERTAIN"]
    assert uncertainty, "request was dispatched and outcome cannot be established"


def test_unparseable_gateway_body_is_explicit_not_silent(run_once):
    def broken(request):
        raise HTTPError(
            url="http://gateway.test/ask",
            code=502,
            msg="Bad Gateway",
            hdrs=None,
            fp=io.BytesIO(b"<html>proxy error</html>"),
        )

    code, task, added = run_once(broken)
    assert code == "GATEWAY_UNCLASSIFIED_RESPONSE"
    assert task.failure_code == "GATEWAY_UNCLASSIFIED_RESPONSE"
    assert code != "GATEWAY_UNAVAILABLE", "a 502 with a body is a response, not a reachability failure"
