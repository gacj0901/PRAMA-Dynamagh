"""Authenticated operator CLI for one bounded bootstrap grant."""
from __future__ import annotations

import argparse
import json
from decimal import Decimal

from app.authority.bootstrap import create_bootstrap_authority
from app.persistence.database import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(description="Create one explicit cold-start bootstrap authority")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--authority-profile-id", required=True)
    parser.add_argument("--policy-id", required=True)
    parser.add_argument("--max-actions", type=int, default=1)
    parser.add_argument("--max-spend-usdc", default="0.010000")
    parser.add_argument("--created-by", default="operator")
    args = parser.parse_args()
    session = SessionLocal()
    try:
        grant = create_bootstrap_authority(
            session,
            agent_identity_id=args.agent_id,
            authority_profile_id=args.authority_profile_id,
            policy_id=args.policy_id,
            max_actions=args.max_actions,
            max_spend_usdc=Decimal(args.max_spend_usdc),
            created_by=args.created_by,
        )
        session.commit()
        print(json.dumps({
            "bootstrap_authority_id": grant.bootstrap_authority_id,
            "agent_id": grant.agent_identity_id,
            "authority_profile_id": grant.authority_profile_id,
            "policy_id": grant.policy_id,
            "status": grant.status,
            "enabled": grant.enabled,
            "max_actions": grant.max_actions,
            "remaining": grant.max_actions - grant.consumed_actions,
            "max_spend_usdc": str(grant.max_spend_usdc),
            "authority_hash": grant.authority_hash,
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
