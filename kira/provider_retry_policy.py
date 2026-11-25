"""Explicit retry and failover decisions for provider request execution."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class RetryDecision:
    continue_with_alternative: bool
    retry_same_target: bool
    retryable: bool
    reason: str

class ProviderRetryPolicy:
    """Never replay ambiguous model requests without an explicit repeatability guarantee.

    Permanent provider-specific errors may still be recovered by a different
    configured provider. Partial output and cancellation terminate the turn.
    """
    def decide(self, error: BaseException, *, request_repeatable: bool,
               partial_output: bool = False, cancelled: bool = False) -> RetryDecision:
        retryable = bool(getattr(error, "retryable", True))
        kind = str(getattr(error, "kind", "unexpected") or "unexpected")
        if cancelled:
            return RetryDecision(False, False, retryable, "cancelled")
        if partial_output:
            return RetryDecision(False, False, retryable, "partial_output_not_replayable")
        # A timeout/5xx alone does not prove the remote service did not process it.
        same_target = bool(retryable and request_repeatable)
        reason = ("retry_same_target" if same_target else
                  "alternate_target_only" if retryable else
                  f"permanent_{kind}_alternate_target_only")
        return RetryDecision(True, same_target, retryable, reason)
