from __future__ import annotations

import json
import os

from .infrai_client import InfraiClient
from .models import PropertyOnboardingRequest
from .onboarding_service import PropertyDomainOnboardingService


def main() -> None:
    infrai = InfraiClient()
    service = PropertyDomainOnboardingService(
        infrai=infrai,
        webhook_secret=os.environ["DOMAIN_WEBHOOK_SECRET"],
    )
    request = PropertyOnboardingRequest(
        tenant_slug="greenview",
        custom_domain="portal.greenviewpm.com",
        app_target="tenant-app.example.net",
        callback_url="https://ops.example.com/webhooks/domain-verification",
        vendor="property-platform",
    )
    result = service.onboard(request)
    body = json.dumps({"domain": result.domain, "status": "verified"}).encode("utf-8")
    signature = service.webhook_verifier.sign(body)
    receipt = service.accept_verification_callback(body, signature)
    print(json.dumps({"onboarding": result.model_dump(), "verification_receipt": receipt.model_dump()}, indent=2))


if __name__ == "__main__":
    main()
