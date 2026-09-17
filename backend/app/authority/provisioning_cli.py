"""Authenticated operator CLI for canonical subject provisioning.

This narrow administrative surface is intended to run through the deployed
service's authenticated Railway SSH session.  It never activates a policy or
starts an acquisition.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal

from app.authority.provisioning import provision_autonomous_subject
from app.persistence.database import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision one autonomous authority subject")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--policy-name", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--max-payment-usdc", default="0.010000")
    parser.add_argument("--cadence-seconds", type=int, default=900)
    parser.add_argument("--created-by", default="operator")
    parser.add_argument("--principal-id")
    args = parser.parse_args()
    session = SessionLocal()
    try:
        result = provision_autonomous_subject(
            session,
            agent_id=args.agent_id,
            name=args.name,
            policy_name=args.policy_name,
            title=args.title,
            instruction=args.instruction,
            max_payment_usdc=Decimal(args.max_payment_usdc),
            cadence_seconds=args.cadence_seconds,
            created_by=args.created_by,
            principal_id=args.principal_id,
        )
        session.commit()
        print(json.dumps({
            "agent_id": result.identity.agent_id,
            "policy_id": result.policy.policy_id,
            "policy_state": result.policy.state,
            "policy_enabled": result.policy.enabled,
            "authority_profile_id": result.profile.authority_profile_id,
            "authority_profile_version": result.profile.version,
            "origin": result.identity.origin,
        }, sort_keys=True))
        return 0
    except Exception as error:
        session.rollback()
        print(json.dumps({"error": str(error)}))
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
