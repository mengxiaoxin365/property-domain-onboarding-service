from __future__ import annotations

import os
from typing import List

from .infrai_client import InfraiClient
from .models import DomainPlan, OnboardingResult, PropertyFeatureRecord, PropertyOnboardingRequest, VerificationReceipt
from .webhook_verifier import DomainVerificationWebhookVerifier


class PropertyDomainOnboardingService:
    def __init__(self, infrai: InfraiClient, webhook_secret: str):
        self.infrai = infrai
        self.webhook_verifier = DomainVerificationWebhookVerifier(webhook_secret)

    def build_plan(self, request: PropertyOnboardingRequest) -> DomainPlan:
        metadata = {
            "tenant_slug": request.tenant_slug,
            "workflow": "property_domain_onboarding",
        }
        portal_record = PropertyFeatureRecord(
            feature="maintenance",
            record_type="CNAME",
            name=request.custom_domain,
            content=request.app_target,
        )
        feature_records: List[PropertyFeatureRecord] = [
            PropertyFeatureRecord(
                feature="maintenance",
                record_type="TXT",
                name=f"maintenance.{request.custom_domain}",
                content=f"tenant={request.tenant_slug};module=maintenance",
            ),
            PropertyFeatureRecord(
                feature="documents",
                record_type="TXT",
                name=f"documents.{request.custom_domain}",
                content=f"tenant={request.tenant_slug};module=documents",
            ),
            PropertyFeatureRecord(
                feature="inspections",
                record_type="TXT",
                name=f"inspections.{request.custom_domain}",
                content=f"tenant={request.tenant_slug};module=inspections",
            ),
        ]
        return DomainPlan(
            domain=request.custom_domain,
            portal_record=portal_record,
            feature_records=feature_records,
            metadata=metadata,
        )

    def onboard(self, request: PropertyOnboardingRequest) -> OnboardingResult:
        plan = self.build_plan(request)
        add_payload = {
            "domain": plan.domain,
            "metadata": plan.metadata,
        }
        if request.vendor:
            add_payload["vendor"] = request.vendor
        if request.account_id:
            add_payload["account_id"] = request.account_id

        add_env = self.infrai.dns_domain_add(add_payload)
        zone_id = add_env["data"]["zone_id"]

        records_written: List[PropertyFeatureRecord] = []
        for record in [plan.portal_record, *plan.feature_records]:
            self.infrai.dns_record_upsert(
                {
                    "zone_id": zone_id,
                    "record_type": record.record_type,
                    "name": record.name,
                    "content": record.content,
                    "ttl": record.ttl,
                    "metadata": {
                        "feature": record.feature,
                        "tenant_slug": request.tenant_slug,
                    },
                }
            )
            records_written.append(record)

        webhook_env = self.infrai.account_webhooks_register(
            {
                "url": request.callback_url,
                "events": ["dns.domain.verified"],
                "description": f"Property domain verification for {request.tenant_slug}",
                "secret": os.environ["DOMAIN_WEBHOOK_SECRET"],
            }
        )

        self.infrai.dns_domain_verify({"domain": request.custom_domain})

        webhook_id = webhook_env["data"].get("id") if isinstance(webhook_env.get("data"), dict) else None
        return OnboardingResult(
            domain=request.custom_domain,
            zone_id=zone_id,
            records_written=records_written,
            webhook_id=webhook_id,
            verification_requested=True,
        )

    def accept_verification_callback(self, body: bytes, signature: str) -> VerificationReceipt:
        return self.webhook_verifier.verify_event(body, signature)
