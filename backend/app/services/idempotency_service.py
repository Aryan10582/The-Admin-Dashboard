from dataclasses import dataclass


@dataclass(frozen=True)
class IdempotencyContext:
    key: str
    operation: str


def build_idempotency_context(key: str, operation: str) -> IdempotencyContext:
    return IdempotencyContext(key=key, operation=operation)
