from __future__ import annotations

import hashlib
import hmac
import json
from typing import Optional

from .models import VerificationEvent, VerificationReceipt


class WebhookVerificationError(Exception):
    pass


class DomainVerificationWebhookVerifier:
    def __init__(self, secret: str):
        self.secret = secret.encode("utf-8")

    def sign(self, body: bytes) -> str:
        return hmac.new(self.secret, body, hashlib.sha256).hexdigest()

    def verify_event(self, body: bytes, signature: Optional[str]) -> VerificationReceipt:
        expected = self.sign(body)
        if not signature or not hmac.compare_digest(expected, signature):
            raise WebhookVerificationError("invalid signature")
        payload = json.loads(body.decode("utf-8"))
        event = VerificationEvent.model_validate(payload)
        return VerificationReceipt(domain=event.domain, status=event.status, accepted=True)
