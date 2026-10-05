from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class PropertyFeatureRecord(BaseModel):
    feature: Literal["maintenance", "documents", "inspections"]
    record_type: Literal["TXT", "CNAME"]
    name: str
    content: str
    ttl: int = 300


class PropertyOnboardingRequest(BaseModel):
    tenant_slug: str = Field(min_length=1)
    custom_domain: str = Field(min_length=1)
    app_target: str = Field(min_length=1)
    callback_url: str = Field(min_length=1)
    vendor: Optional[str] = None
    account_id: Optional[str] = None


class DomainPlan(BaseModel):
    domain: str
    portal_record: PropertyFeatureRecord
    feature_records: List[PropertyFeatureRecord]
    metadata: Dict[str, str]


class OnboardingResult(BaseModel):
    domain: str
    zone_id: str
    records_written: List[PropertyFeatureRecord]
    webhook_id: Optional[str] = None
    verification_requested: bool = True


class VerificationEvent(BaseModel):
    domain: str
    status: str


class VerificationReceipt(BaseModel):
    domain: str
    status: str
    accepted: bool
