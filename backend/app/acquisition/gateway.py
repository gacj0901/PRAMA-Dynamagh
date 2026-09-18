"""Telegraph Gateway implementation of the provider-neutral Access Plane."""

import json
import os
from decimal import Decimal
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.acquisition.contracts import AcquisitionResult, X402_PAYMENT_RAIL


class AcquisitionAdapterError(RuntimeError):
    """An adapter failure with the worker's existing failure taxonomy."""

    def __init__(
        self,
        code: str,
        *,
        raw_payload: Any = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.raw_payload = raw_payload
        self.http_status = http_status


class TelegraphGatewayAdapter:
    """Perform one Telegraph acquisition through the existing Gateway /ask API.

    This class owns only request construction, HTTP transport and response
    normalization. Accounting, authority, persistence and downstream
    Evidence/Decision/Ticket handling remain in the worker.
    """

    provider = "TELEGRAPH"
    access_mechanism = "GATEWAY"
    payment_rail = X402_PAYMENT_RAIL

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int = 120,
        internal_token: str | None = None,
        urlopen_fn: Callable[..., Any] = urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.internal_token = internal_token
        self._urlopen = urlopen_fn

    @classmethod
    def from_environment(
        cls,
        *,
        timeout_seconds: int = 120,
        urlopen_fn: Callable[..., Any] = urlopen,
    ) -> "TelegraphGatewayAdapter":
        return cls(
            base_url=os.environ["GATEWAY_URL"],
            timeout_seconds=timeout_seconds,
            internal_token=os.environ.get("PRAMA_GATEWAY_INTERNAL_TOKEN"),
            urlopen_fn=urlopen_fn,
        )

    def acquire(
        self,
        *,
        query: str,
        requested_intent: str | None,
        causal_request_id: str,
        budget_usdc: Decimal,
    ) -> AcquisitionResult:
        payload = {
            "query": query,
            "context": {"requested_intent": requested_intent} if requested_intent else {},
            "causal_request_id": causal_request_id,
            "budget_usdc": str(budget_usdc),
        }
        headers = {"content-type": "application/json"}
        if self.internal_token:
            headers["x-prama-internal-token"] = self.internal_token
        request = Request(
            self.base_url + "/ask",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with self._urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read())
        except HTTPError as error:
            body = error.read()
            parsed: Any
            try:
                parsed = json.loads(body)
            except (ValueError, TypeError):
                parsed = None
            code = parsed.get("code") if isinstance(parsed, dict) else None
            raw_payload = {
                "gateway_http_status": error.code,
                "gateway_error_body": body.decode("utf-8", "replace")[:2048],
            }
            raise AcquisitionAdapterError(
                code or "GATEWAY_UNCLASSIFIED_RESPONSE",
                raw_payload=raw_payload,
                http_status=error.code,
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise AcquisitionAdapterError("GATEWAY_UNAVAILABLE") from error

        normalized_raw = raw if isinstance(raw, dict) else {"gateway_response": raw}
        if not isinstance(raw, dict) or not all(raw.get(key) for key in ("miner_id", "intent", "signal_hash")):
            raise AcquisitionAdapterError("TELEGRAPH_INVALID_RESPONSE", raw_payload=normalized_raw)
        cost_value = (raw.get("payment") or {}).get("amount_usdc", raw.get("cost_usd"))
        if cost_value is None:
            raise AcquisitionAdapterError("PAYMENT_COST_UNAVAILABLE", raw_payload=normalized_raw)
        actual = Decimal(str(cost_value))
        if not actual.is_finite() or actual < 0 or actual > budget_usdc or actual.as_tuple().exponent < -6:
            raise AcquisitionAdapterError("SINGLE_ACQUISITION_BUDGET_EXCEEDED", raw_payload=normalized_raw)
        return AcquisitionResult(
            provider=self.provider,
            miner_id=str(raw["miner_id"]),
            miner_name=raw.get("miner_name"),
            intent=raw.get("intent"),
            signal_hash=raw.get("signal_hash"),
            cost_usdc=actual,
            duration_ms=raw.get("duration_ms"),
            reasoning=raw.get("reasoning"),
            warnings=raw.get("warnings") or [],
            raw_payload=normalized_raw,
            access_mechanism=self.access_mechanism,
            payment_rail=self.payment_rail,
        )
