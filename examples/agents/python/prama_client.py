"""One authorized native x402 operation. No keys, auto-repayment or logging."""
import base64
import copy
import json
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit
import httpx


@dataclass(frozen=True)
class Policy:
    network: str
    asset: str
    recipient: str
    domain_name: str = "USDC"
    domain_version: str = "2"
    max_request_atomic: int = 50_000
    max_session_atomic: int = 250_000


class PramaClient:
    def __init__(self, *, policy, signer, checkpoint, endpoint="https://prama-dynamagh.up.railway.app/v1/public/ask", http=None):
        self.policy, self.signer, self.checkpoint = policy, signer, checkpoint
        self.endpoint = endpoint
        if urlsplit(endpoint).scheme != "https":
            raise ValueError("HTTPS required")
        self.http = http or httpx.Client(timeout=30, follow_redirects=False)
        self.used = False

    def request(self, requested_intent, query, *, polls=30, interval=2):
        if self.used:
            raise RuntimeError("This operation client is single-use; no automatic repayment")
        self.used = True
        body = {"requested_intent": requested_intent, "query": query}
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        initial = self.http.post(self.endpoint, json=body, headers=headers)
        if initial.status_code != 402:
            raise RuntimeError("Expected 402; stopped without signing")
        challenge = json.loads(base64.b64decode(initial.headers["payment-required"], validate=True))
        if challenge.get("x402Version") != 2 or len(challenge.get("accepts", [])) != 1:
            raise ValueError("Unsupported challenge")
        r = challenge["accepts"][0]
        p = self.policy
        amount = r.get("amount", "")
        if not isinstance(amount, str) or not amount.isdecimal():
            raise ValueError("Invalid amount")
        if not (0 < int(amount) <= min(p.max_request_atomic, p.max_session_atomic)):
            raise ValueError("Payment ceiling exceeded")
        if (r.get("scheme") != "exact" or r.get("network") != p.network
            or r.get("asset", "").lower() != p.asset.lower() or r.get("payTo", "").lower() != p.recipient.lower()
            or r.get("extra", {}).get("name") != p.domain_name or r.get("extra", {}).get("version") != p.domain_version
            or challenge.get("resource", {}).get("url") != self.endpoint
            or ("resource" in r and r["resource"] != self.endpoint)):
            raise ValueError("Unapproved payment terms")
        # The callback owns wallet policy and uses a compatible x402 SDK.
        # It returns the encoded PAYMENT-SIGNATURE header; never expose it to an LLM.
        signature = self.signer(copy.deepcopy(challenge))
        self.checkpoint({"state": "PAYMENT_SUBMISSION_PENDING", "idempotency_key": headers["Idempotency-Key"]})
        paid = self.http.post(self.endpoint, json=body, headers={**headers, "PAYMENT-SIGNATURE": signature})
        if paid.status_code != 202:
            raise RuntimeError("Paid response failed or ambiguous; STOP, do not pay again")
        accepted = paid.json()
        self.checkpoint(accepted)  # Store privately before polling; contains one-time capability.
        mid = str(uuid.UUID(accepted["mandate_id"]))
        url = accepted["result_endpoint"]
        if url != self.endpoint + "/" + mid + "/result" or not accepted.get("result_capability"):
            raise ValueError("Invalid capability result route; STOP")
        for _ in range(polls):
            response = self.http.get(url, headers={"X-PRAMA-Result-Capability": accepted["result_capability"]})
            if response.status_code != 200:
                raise RuntimeError("Result retrieval failed; retain checkpoint, never repay")
            result = response.json()
            status = result.get("consumer_result", {}).get("status")
            if status in {"DELIVERED", "NOT_AVAILABLE"}:
                return result
            if status != "PENDING":
                raise RuntimeError("Unknown result state")
            time.sleep(interval)
        raise TimeoutError("Polling limit; preserve capability and never repay")
