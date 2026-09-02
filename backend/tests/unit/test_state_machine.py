import pytest

from app.domain.mandates import MandateStatus
from app.domain.state_machine import ALLOWED_TRANSITIONS


def test_execution_path_is_explicit() -> None:
    assert MandateStatus.PLANNED in ALLOWED_TRANSITIONS[MandateStatus.RECEIVED]
    path = [MandateStatus.RECEIVED, MandateStatus.PLANNED, MandateStatus.ACQUIRING, MandateStatus.EVALUATING, MandateStatus.DECIDING, MandateStatus.DECIDED, MandateStatus.TICKETED]
    assert all(target in ALLOWED_TRANSITIONS[current] for current, target in zip(path, path[1:]))
    assert MandateStatus.TICKETED not in ALLOWED_TRANSITIONS[MandateStatus.DECIDING]


def test_terminal_states_cannot_transition() -> None:
    assert ALLOWED_TRANSITIONS[MandateStatus.TICKETED] == set()
    assert ALLOWED_TRANSITIONS[MandateStatus.FAILED] == set()
