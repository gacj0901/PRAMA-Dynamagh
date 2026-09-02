import pytest

from app.domain.mandates import MandateStatus
from app.domain.state_machine import ALLOWED_TRANSITIONS


def test_execution_path_is_explicit() -> None:
    assert MandateStatus.PLANNED in ALLOWED_TRANSITIONS[MandateStatus.RECEIVED]
    assert MandateStatus.TICKETED in ALLOWED_TRANSITIONS[MandateStatus.DECIDING]


def test_terminal_states_cannot_transition() -> None:
    assert ALLOWED_TRANSITIONS[MandateStatus.TICKETED] == set()
    assert ALLOWED_TRANSITIONS[MandateStatus.FAILED] == set()
