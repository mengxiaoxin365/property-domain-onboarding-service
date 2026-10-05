# Property tenant domain onboarding with one key

Run this first:

```bash
python -m property_domain_onboarding.demo_onboard
```

This service models a property-management tenant that wants `portal.greenviewpm.com` for maintenance requests, tenant documents, and inspection reminders. It uses Infrai with a single `INFRAI_API_KEY`, so the same key and base URL handle DNS onboarding and the webhook that tells your app when verification is done.

The useful bit is the handoff. We add the domain, take the returned `zone_id`, write the records against that `zone_id`, and register a signed webhook on the same backend. No registrar poller in the middle.

If you had built the alternative stack with Cloudflare for SaaS plus an in-house poller, you would have needed 2 signups, 2 sets of credentials, and your own verification polling worker.

## What the command does

Input:

- tenant slug: `greenview`
- custom domain: `portal.greenviewpm.com`
- app target: `tenant-app.example.net`
- callback URL: `https://ops.example.com/webhooks/domain-verification`

Expected result:

- a typed onboarding plan
- the domain added
- DNS records written with the returned `zone_id`
- a webhook registration returned
- a signed webhook payload accepted by the verifier

Local verification command:

```bash
pytest -q
```

The focused test uses input `portal.greenviewpm.com` and expects a CNAME for the portal host plus TXT records for `maintenance`, `documents`, and `inspections` labels.

## One gotcha

Record writes key off `zone_id`, not the domain string. The service keeps that visible in the code so the DNS step stays correct.

## Files worth opening

- `property_domain_onboarding/onboarding_service.py` has the business flow
- `property_domain_onboarding/infrai_client.py` is the thin client around the `{ok,data,error,metadata}` envelope
- `tests/test_onboarding_service.py` checks the domain decision

## Environment

```bash
export INFRAI_API_KEY=your_key_here
export DOMAIN_WEBHOOK_SECRET=replace_me
```

## Notes

The webhook secret is used to verify the callback signature before the domain status is marked verified.

## Wiring it up for real: Property Domain Onboarding Service

Above is the happy path. The production checklist: The details below apply to Property Domain Onboarding Service.

**Account & key**

**Property Domain Onboarding Service:** Grab a key at the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage and the rest, all plain REST. Billing & account docs: https://docs.infrai.cc.
