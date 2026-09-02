"""Structured PolicyViolation exceptions and standardized error codes."""

from typing import Any


class PolicyViolation(Exception):
    """Base exception for deterministic policy and verification failures."""

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 403,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.code,
            "message": self.message,
            "http_status": self.http_status,
            **self.details,
        }


# 403 Forbidden: Policy bounds checks
class PolicySpendCapExceeded(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_SPEND_CAP_EXCEEDED", message, http_status=403, details=details)


class PolicyCategoryNotAllowed(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_CATEGORY_NOT_ALLOWED", message, http_status=403, details=details)


class PolicyMerchantNotAllowed(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_MERCHANT_NOT_ALLOWED", message, http_status=403, details=details)


class PolicyIntentExpired(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_INTENT_EXPIRED", message, http_status=403, details=details)


class PolicyIntentNotYetValid(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_INTENT_NOT_YET_VALID", message, http_status=403, details=details)


class PolicyTransactionLimitReached(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_TRANSACTION_LIMIT_REACHED", message, http_status=403, details=details)


# 409 Conflict: Cryptographic & state mismatch
class PolicyReplayDetected(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_REPLAY_DETECTED", message, http_status=409, details=details)


class PolicyCartExpired(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_CART_EXPIRED", message, http_status=409, details=details)


class PolicyIntentSignatureInvalid(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_INTENT_SIGNATURE_INVALID", message, http_status=409, details=details)


class PolicyCartSignatureInvalid(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_CART_SIGNATURE_INVALID", message, http_status=409, details=details)


class PolicyMandateSignatureInvalid(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_MANDATE_SIGNATURE_INVALID", message, http_status=409, details=details)


class PolicyReceiptSignatureInvalid(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_RECEIPT_SIGNATURE_INVALID", message, http_status=409, details=details)


class PolicyCartHashMismatch(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_CART_HASH_MISMATCH", message, http_status=409, details=details)


# 404 Not Found: Catalog lookup failure
class CatalogSkuNotFound(PolicyViolation):
    def __init__(self, sku: str) -> None:
        super().__init__(
            "CATALOG_SKU_NOT_FOUND",
            f"Requested SKU '{sku}' does not exist in the merchant catalog.",
            http_status=404,
            details={"sku": sku},
        )


# 400 Bad Request: Webhook / Signature failure
class WebhookSignatureInvalid(PolicyViolation):
    def __init__(self, message: str = "Webhook HMAC signature verification failed.") -> None:
        super().__init__("SIGNATURE_VERIFICATION_FAILED", message, http_status=400)


# 409 Conflict: Mandate state transition failure (FSM)
class PolicyMandateStateInvalid(PolicyViolation):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("POLICY_MANDATE_STATE_INVALID", message, http_status=409, details=details)

