import json

from property_domain_onboarding.models import PropertyOnboardingRequest
from property_domain_onboarding.onboarding_service import PropertyDomainOnboardingService
from property_domain_onboarding import demo_onboard


class StubInfraiClient:
    def __init__(self):
        self.calls = []

    def dns_domain_add(self, payload):
        self.calls.append(("dns_domain_add", payload))
        return {"ok": True, "data": {"zone_id": "zone_123"}, "error": None, "metadata": {}}

    def dns_record_upsert(self, payload):
        self.calls.append(("dns_record_upsert", payload))
        return {"ok": True, "data": {"record_id": "rec_123"}, "error": None, "metadata": {}}

    def account_webhooks_register(self, payload):
        self.calls.append(("account_webhooks_register", payload))
        return {"ok": True, "data": {"id": "wh_123"}, "error": None, "metadata": {}}

    def dns_domain_verify(self, payload):
        self.calls.append(("dns_domain_verify", payload))
        return {"ok": True, "data": {"verified": True}, "error": None, "metadata": {}}


def test_property_onboarding_writes_zone_records_and_verifies_callback(monkeypatch):
    monkeypatch.setenv("DOMAIN_WEBHOOK_SECRET", "topsecret")
    client = StubInfraiClient()
    service = PropertyDomainOnboardingService(client, webhook_secret="topsecret")
    request = PropertyOnboardingRequest(
        tenant_slug="greenview",
        custom_domain="portal.greenviewpm.com",
        app_target="tenant-app.example.net",
        callback_url="https://ops.example.com/webhooks/domain-verification",
    )

    result = service.onboard(request)

    assert result.zone_id == "zone_123"
    assert result.webhook_id == "wh_123"
    upserts = [payload for name, payload in client.calls if name == "dns_record_upsert"]
    assert len(upserts) == 4
    assert upserts[0]["zone_id"] == "zone_123"
    assert upserts[0]["record_type"] == "CNAME"
    assert upserts[0]["name"] == "portal.greenviewpm.com"
    assert upserts[0]["content"] == "tenant-app.example.net"
    assert [u["name"] for u in upserts[1:]] == [
        "maintenance.portal.greenviewpm.com",
        "documents.portal.greenviewpm.com",
        "inspections.portal.greenviewpm.com",
    ]
    assert all(u["record_type"] == "TXT" for u in upserts[1:])

    body = json.dumps({"domain": "portal.greenviewpm.com", "status": "verified"}).encode("utf-8")
    signature = service.webhook_verifier.sign(body)
    receipt = service.accept_verification_callback(body, signature)
    assert receipt.accepted is True
    assert receipt.status == "verified"


def test_demo_accepts_signed_verification_callback(monkeypatch, capsys):
    monkeypatch.setenv("DOMAIN_WEBHOOK_SECRET", "topsecret")
    monkeypatch.setattr(demo_onboard, "InfraiClient", StubInfraiClient)

    demo_onboard.main()

    output = json.loads(capsys.readouterr().out)
    assert output["onboarding"]["domain"] == "portal.greenviewpm.com"
    assert output["verification_receipt"] == {
        "domain": "portal.greenviewpm.com",
        "status": "verified",
        "accepted": True,
    }
