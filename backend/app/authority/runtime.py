"""Non-enforcing checkpoints beside committed paid-workflow artifacts.

Checkpoint records describe existing authority or explicit unavailability.
They are distinct from the frozen typed E3 and G13 policies themselves.
"""
import logging
from sqlalchemy import text
from app.persistence.database import SessionLocal
from app.domain.mandates import Mandate, Decision, EpistemicEvaluation, AutonomyRun, PublicManualSpendReservation
from app.policy_gate.substrate import PolicyEvaluationCore, persist_policy_evaluation

logger = logging.getLogger(__name__)
VERSION = "authority-shadow-checkpoint-v0.1"


def checkpoint(mandate_id, family, phase, action_id, result, details, refs=()):
    return PolicyEvaluationCore(
        policy_id="AUTHORITY_SHADOW_"+family,
        policy_version=VERSION,
        policy_type="AUTHORITY_CHECKPOINT",
        policy_subject_type="MANDATE",
        policy_subject_id=mandate_id,
        observation_refs=tuple(refs),
        observation_contract_versions={"checkpoint":VERSION},
        input_core={"mandate_id":mandate_id,"family":family,"phase":phase,"action_id":action_id,"details":details},
        triggered_rule_ids=("OBSERVE_PERSISTED_AUTHORITY" if result not in {"UNAVAILABLE","NOT_APPLICABLE"} else result,),
        result=result,
        result_core={"family":family,"observed_result":result,"enforcement":"SHADOW_ONLY","details":details},
    )


def _observe(session, mandate_id, family, phase, acquisition_id):
    mandate = session.get(Mandate,mandate_id)
    if mandate is None: raise ValueError("MANDATE_MISSING")
    refs = []
    details = {}
    if family == "CD":
        e1 = session.query(EpistemicEvaluation).filter_by(mandate_id=mandate_id).order_by(EpistemicEvaluation.created_at.desc(),EpistemicEvaluation.evaluation_id.desc()).first()
        decision = session.query(Decision).filter_by(mandate_id=mandate_id).first()
        if e1 is not None:
            from app.authority.epistemic import EpistemicPolicyInput,evaluate_epistemic_policy
            core = evaluate_epistemic_policy(EpistemicPolicyInput.from_evaluation(e1))
            persist_policy_evaluation(session,core)
            refs.append(core.policy_evaluation_id)
            details.update(typed_e1_evaluation_id=e1.evaluation_id,typed_policy_result=core.result)
        details['typed_e1_available'] = e1 is not None
        if decision:
            refs += [decision.decision_id,decision.evaluation_id]
            result = decision.state
            details.update(source='PERSISTED_DECISION',policy_version=decision.policy_version,evidence_set_hash=decision.evidence_set_hash)
        else:
            result = 'UNAVAILABLE'
            details.update(reason='PERSISTED_DECISION_MISSING',absence_imputed=False)
    elif family == "G12":
        reservation = session.get(PublicManualSpendReservation,mandate_id)
        if reservation is None:
            result='UNAVAILABLE';details={'reason':'RESERVATION_MISSING'}
        else:
            result=reservation.status
            details={"spend_date":reservation.spend_date.isoformat(),"reserved_usdc":str(reservation.reserved_usdc),"actual_spend_usdc":str(reservation.actual_spend_usdc) if reservation.actual_spend_usdc is not None else None,"origin":reservation.origin,"authority":"EXISTING_G12_ENFORCED","authorization_recomputed":False}
            refs=[mandate_id]
    else:
        run = session.query(AutonomyRun).filter_by(mandate_id=mandate_id).one_or_none()
        if run is None:
            result='NOT_APPLICABLE';details={'reason':'NO_AUTONOMY_RUN'}
        else:
            agent = run.agent_identity_id or mandate.agent_identity_id
            if not agent: raise ValueError('AUTONOMY_AGENT_IDENTITY_MISSING')
            from app.agents.observation import build_o_agent_stream
            from app.authority.autonomy import G13PolicyInput,evaluate_g13_policy
            observations=build_o_agent_stream(session,agent,run_id=run.run_id)
            # Preserve the observer's canonical ordering and complete sequence.
            core=evaluate_g13_policy(G13PolicyInput.from_observations(agent,observations,trajectory_lineage_id=f'o-agent-v0:{agent}:run:{run.run_id}'))
            persist_policy_evaluation(session,core)
            result=core.result;refs=[run.run_id,core.policy_evaluation_id]
            details={'run_id':run.run_id,'agent_id':agent,'policy_version':core.policy_version,'policy_result_hash':core.result_hash}
    core=checkpoint(mandate_id,family,phase,acquisition_id,result,details,refs)
    persist_policy_evaluation(session,core)
    return core.policy_evaluation_id


def observe_authority_shadow(mandate_id, *, phase, acquisition_id=None):
    """Own transactions; neither policy results nor exceptions affect payment.

    An unavailable checkpoint is retried as a diagnostic PolicyEvaluation.
    If PostgreSQL itself is unavailable, persistence is impossible: emit a
    sanitized log and retain that operational limitation, never fabricate a row.
    """
    identities=[]
    for family in ('CD','G12','CDG'):
        session=None
        try:
            session=SessionLocal()
            session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            identities.append(_observe(session,mandate_id,family,phase,acquisition_id))
            session.commit()
        except Exception as error:
            if session is not None:
                try: session.rollback()
                except Exception: pass
            logger.warning('AUTHORITY_SHADOW_UNAVAILABLE mandate_id=%s family=%s error=%s',mandate_id,family,type(error).__name__)
            fallback=None
            try:
                fallback=SessionLocal()
                fallback.execute(text("SET LOCAL statement_timeout = '2000ms'"))
                core=checkpoint(mandate_id,family,phase,acquisition_id,'UNAVAILABLE',{'reason':'CHECKPOINT_FAILED','error_class':type(error).__name__})
                persist_policy_evaluation(fallback,core)
                fallback.commit()
                identities.append(core.policy_evaluation_id)
            except Exception:
                if fallback is not None:
                    try: fallback.rollback()
                    except Exception: pass
                logger.error('AUTHORITY_SHADOW_UNAVAILABLE_NOT_PERSISTED mandate_id=%s family=%s',mandate_id,family)
            finally:
                if fallback is not None:
                    try: fallback.close()
                    except Exception: pass
        finally:
            if session is not None:
                try: session.close()
                except Exception: pass
    return identities
