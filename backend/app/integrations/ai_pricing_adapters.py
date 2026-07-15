from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json

from app.core.config import settings


@dataclass(frozen=True)
class NormalizedPricing:
    provider: str
    provider_model_id: str | None
    pricing_scope_code: str | None
    currency: str | None
    input_token_price: Decimal | None
    output_token_price: Decimal | None
    pricing_unit_tokens: int | None
    source_reference: str | None
    source_effective_at: datetime | None
    source_fingerprint: str | None
    is_authoritative: bool
    is_ambiguous: bool = False
    safe_error: str | None = None


class AIProviderPricingAdapter:
    adapter_code = "base"

    def supports_provider(self, provider: str) -> bool:
        raise NotImplementedError

    def fetch_pricing(self, *, provider: str, provider_model_id: str, pricing_scope_code: str, scenario: str | None = None) -> NormalizedPricing:
        raise NotImplementedError

    @staticmethod
    def source_fingerprint(payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DevelopmentMockPricingAdapter(AIProviderPricingAdapter):
    adapter_code = "development_mock"

    def supports_provider(self, provider: str) -> bool:
        return provider == "mock-ai"

    def fetch_pricing(self, *, provider: str, provider_model_id: str, pricing_scope_code: str, scenario: str | None = None) -> NormalizedPricing:
        if settings.environment.lower() == "production" or not settings.ai_pricing_mock_adapter_enabled:
            return self._unsupported(provider, pricing_scope_code, "Development mock pricing adapter is disabled")
        scenario = scenario or "unchanged"
        now = datetime.now(timezone.utc).replace(microsecond=0)
        base = {
            "provider": provider,
            "provider_model_id": provider_model_id,
            "pricing_scope_code": pricing_scope_code,
            "currency": "USD",
            "input_token_price": Decimal("2.50000000"),
            "output_token_price": Decimal("10.00000000"),
            "pricing_unit_tokens": 1000000,
            "source_effective_at": now,
            "source_reference": f"mock://pricing/{scenario}",
        }
        if scenario == "unsupported_provider":
            return self._unsupported(provider, pricing_scope_code, "Unsupported provider")
        if scenario == "temporary_5xx":
            return self._unavailable(provider, pricing_scope_code, "Mock temporary source failure")
        if scenario == "timeout":
            return self._unavailable(provider, pricing_scope_code, "Mock pricing source timeout")
        if scenario == "malformed_response":
            return NormalizedPricing(provider=provider, provider_model_id=None, pricing_scope_code=pricing_scope_code, currency=None, input_token_price=None, output_token_price=None, pricing_unit_tokens=None, source_reference="mock://pricing/malformed", source_effective_at=None, source_fingerprint=None, is_authoritative=False, safe_error="Malformed pricing response")
        if scenario == "input_price_changed":
            base["input_token_price"] = Decimal("3.00000000")
        elif scenario == "output_price_changed":
            base["output_token_price"] = Decimal("12.00000000")
        elif scenario == "both_changed":
            base["input_token_price"] = Decimal("3.00000000")
            base["output_token_price"] = Decimal("12.00000000")
        elif scenario == "duplicate_source_fingerprint":
            base["input_token_price"] = Decimal("3.00000000")
            base["source_reference"] = "mock://pricing/fingerprint-stable"
            base["source_effective_at"] = datetime(2030, 1, 1, tzinfo=timezone.utc)
        elif scenario == "future_effective_date":
            base["input_token_price"] = Decimal("3.00000000")
            base["source_effective_at"] = now + timedelta(days=7)
        elif scenario == "missing_currency":
            base["currency"] = None
        elif scenario == "missing_pricing_unit":
            base["pricing_unit_tokens"] = None
        elif scenario == "missing_input_price":
            base["input_token_price"] = None
        elif scenario == "missing_output_price":
            base["output_token_price"] = None
        elif scenario == "unknown_model":
            base["provider_model_id"] = "mock-unknown-model"
        elif scenario == "contradictory_duplicate_entries":
            base["input_token_price"] = Decimal("3.00000000")
            return self._pricing(base, authoritative=False, ambiguous=True, safe_error="Conflicting duplicate pricing entries")
        elif scenario not in {"unchanged", "input_price_changed", "output_price_changed", "both_changed", "duplicate_source_fingerprint", "future_effective_date", "missing_currency", "missing_pricing_unit", "missing_input_price", "missing_output_price", "unknown_model", "contradictory_duplicate_entries"}:
            return self._unsupported(provider, pricing_scope_code, "Unsupported mock pricing scenario")
        return self._pricing(base)

    def _pricing(self, payload: dict, *, authoritative: bool = True, ambiguous: bool = False, safe_error: str | None = None) -> NormalizedPricing:
        fingerprint_payload = {
            "provider": payload.get("provider"),
            "provider_model_id": payload.get("provider_model_id"),
            "pricing_scope_code": payload.get("pricing_scope_code"),
            "currency": payload.get("currency"),
            "input_token_price": str(payload.get("input_token_price")),
            "output_token_price": str(payload.get("output_token_price")),
            "pricing_unit_tokens": payload.get("pricing_unit_tokens"),
            "source_effective_at": payload.get("source_effective_at").isoformat() if payload.get("source_effective_at") else None,
            "source_reference": payload.get("source_reference"),
        }
        return NormalizedPricing(
            provider=payload["provider"],
            provider_model_id=payload.get("provider_model_id"),
            pricing_scope_code=payload.get("pricing_scope_code"),
            currency=payload.get("currency"),
            input_token_price=payload.get("input_token_price"),
            output_token_price=payload.get("output_token_price"),
            pricing_unit_tokens=payload.get("pricing_unit_tokens"),
            source_reference=payload.get("source_reference"),
            source_effective_at=payload.get("source_effective_at"),
            source_fingerprint=self.source_fingerprint(fingerprint_payload),
            is_authoritative=authoritative,
            is_ambiguous=ambiguous,
            safe_error=safe_error,
        )

    @staticmethod
    def _unsupported(provider: str, scope: str, message: str) -> NormalizedPricing:
        return NormalizedPricing(provider=provider, provider_model_id=None, pricing_scope_code=scope, currency=None, input_token_price=None, output_token_price=None, pricing_unit_tokens=None, source_reference=None, source_effective_at=None, source_fingerprint=None, is_authoritative=False, safe_error=message)

    @staticmethod
    def _unavailable(provider: str, scope: str, message: str) -> NormalizedPricing:
        return NormalizedPricing(provider=provider, provider_model_id=None, pricing_scope_code=scope, currency=None, input_token_price=None, output_token_price=None, pricing_unit_tokens=None, source_reference=None, source_effective_at=None, source_fingerprint=None, is_authoritative=False, safe_error=message)


def get_trusted_pricing_adapter(adapter_code: str | None, provider: str) -> AIProviderPricingAdapter | None:
    if settings.environment.lower() == "production":
        return None
    if not settings.ai_pricing_mock_adapter_enabled:
        return None
    adapters: list[AIProviderPricingAdapter] = [DevelopmentMockPricingAdapter()]
    for adapter in adapters:
        if adapter_code and adapter.adapter_code != adapter_code:
            continue
        if adapter.supports_provider(provider):
            return adapter
    return None
