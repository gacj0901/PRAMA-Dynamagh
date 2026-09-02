from sqlalchemy.orm import Session

from app.domain.mandates import Mandate, MandateStatus, MandateTransition

ALLOWED_TRANSITIONS: dict[MandateStatus, set[MandateStatus]] = {
    MandateStatus.RECEIVED: {MandateStatus.PLANNED, MandateStatus.FAILED},
    MandateStatus.PLANNED: {MandateStatus.ACQUIRING, MandateStatus.FAILED},
    MandateStatus.ACQUIRING: {MandateStatus.EVALUATING, MandateStatus.FAILED},
    MandateStatus.EVALUATING: {MandateStatus.DECIDING, MandateStatus.FAILED},
    MandateStatus.DECIDING: {MandateStatus.TICKETED, MandateStatus.FAILED},
    MandateStatus.TICKETED: set(),
    MandateStatus.FAILED: set(),
}


def transition_mandate(session: Session, mandate: Mandate, target: MandateStatus, reason: str | None = None) -> None:
    current = MandateStatus(mandate.status)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid mandate transition: {current.value} -> {target.value}")
    mandate.status = target.value
    session.add(MandateTransition(mandate_id=mandate.mandate_id, from_status=current.value, to_status=target.value, reason=reason))

