"""Explicit retry and failover decisions for provider request execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetryDecision:
    continue_with_alternative: bool
    retry_same_target: bool
    retryable: bool
    reason: str


class ProviderRetryPolicy:
    """Never replay an ambiguous chat request against the same target in one turn.

    Provider retryability describes whether a failure is transient. A failover to
    another configured target is a separate operation: permanent key/model errors
    may still be provider-specific, so a distinct adapter/target can be considered.
    The router independently deduplicates endpoint + model + credential identities.
    """

    def decide(
        self,
        error: BaseException,
        *,
        request_repeatable: bool,
        partial_output: bool = False,
        cancelled: bool = False,
    ) -> RetryDecision:
        retryable = bool(getattr(error, "retryable", True))
        kind = str(getattr(error, "kind", "unexpected") or "unexpected")
        if cancelled:
            return RetryDecision(False, False, retryable, "cancelled")
        if partial_output:
            return RetryDecision(False, False, retryable, "partial_output_not_replayable")
        same_target = bool(retryable and request_repeatable)
        reason = "retry_same_target" if same_target else (
            "alternate_target_only" if retryable else f"permanent_{kind}_alternate_target_only"
        )
        return RetryDecision(True, same_target, retryable, reason)
