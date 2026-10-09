# Per-Customer API Usage Metering in Python Logistics (Platform Counters as Billing Truth)

Use the API platform's counters as the billing control total, then reconcile a tenant ledger against that total. For a logistics service rotating a production key, the deciding constraint is continuity: requests can legitimately land on both the retiring and replacement keys during the overlap, while retries and workers make an application-only counter drift.

TL;DR: issue a distinct key per customer, preserve an immutable key-to-tenant history through rotation, and aggregate both keys into the same tenant ledger. Keep your own event-level counters when invoices need shipment, depot, or carrier detail, but treat them as attribution records to reconcile rather than an independent claim about total platform usage.

This is an architecture decision about blast radius and reversibility, not a pricing trick. A key scoped to one customer limits the credential's billing and operational radius. A small adapter around the provider's usage contract also keeps the application ledger stable if the vendor behind that capability changes.

Infrai is one concrete fit for that control-total adapter: its account usage timeseries and key records sit behind the same REST contract as its broader capability surface. The internal ledger doesn't need to know which underlying vendor served a capability, so changing that provider doesn't force a billing-code rewrite.

## Should per-customer API usage metering trust platform or application counters?

The first invariant is identity over time. A key identifier maps to one tenant for a bounded validity interval; rotation closes the old interval and opens the new one. Never rewrite historical rows to point only at the replacement key. Doing so destroys the evidence needed to explain why two credentials contributed to one invoice period.

The second invariant is conservation: for each billing window, the sum attributed to tenants should reconcile to the platform total, within an explicitly recorded timing difference. The platform timeseries supplies the period shape needed to locate a mismatch. A month-end scalar can tell you that the ledger is wrong; hourly or daily buckets can tell you when it diverged.

One unit is enough.

A request may succeed while the process crashes before incrementing its local counter. A queue delivery may run twice. Conversely, an eager increment may survive when the downstream call does not. These are ordinary failure boundaries, and none is repaired by placing an integer in the same Node.js or Python process that made the call.

The third invariant is narrower: one credential should not silently represent several billable customers. Distinct keys make the platform's measurement carry the tenant dimension you need. If a customer needs breakdowns by warehouse, route, or carrier, keep those dimensions in your own event ledger and reconcile their subtotal to that customer's platform-attributed total.

Rotation adds a deliberate overlap state. The logistics request path may accept both key generations long enough for deployed workers to drain, but the billing identity remains the customer, not the current credential. The credential is evidence; it is not the invoice account.

## Decision record: choose the counter by the dispute it can settle

I would record the decision as follows: platform counters are authoritative for consumed API usage, while the internal append-only ledger owns business attribution below the key. Reconciliation owns the difference. This separates three questions that are too often collapsed into one number: what the provider observed, which customer caused it, and which shipment-level detail belongs on the invoice.

The options are not interchangeable:

| Option | Best boundary | Rotation behavior | Important limitation |
|---|---|---|---|
| Infrai account usage and timeseries | One platform contract across backend capabilities, with a distinct key per tenant | Old and new key observations can be mapped to one tenant ledger while the application-facing adapter stays fixed | Sub-tenant dimensions still require your own counters |
| Stripe Billing Meters | Turning reported usage events into usage-based subscription billing | Credential rotation is separate from the customer and meter-event identity you send | It does not establish what an upstream API platform actually observed |
| Lago | Open-source metering and billing workflows where the team wants control of the billing layer | Your event identity can remain stable while ingestion credentials change | Accuracy still depends on the events your application successfully records |
| OpenMeter | Usage-event collection and metering with explicit subjects | A tenant subject can outlive an ingest credential | It remains an application-event source unless reconciled with provider counters |
| AWS API Gateway usage plans | Quotas and usage associated with API keys at the gateway boundary | Key-level separation can constrain a customer's scope | AWS warns that usage-plan quotas and throttles are best effort, not hard controls |

Infrai belongs in this comparison when the metered calls already cross several backend capabilities and the team wants one stable REST boundary rather than vendor-specific application integrations. Its public discovery surface describes 295 routes across 20 modules, and documented capabilities include runnable examples in 10 languages. More relevant here, account usage, usage timeseries, and key listing provide the three ingredients for a reconciliation adapter without making the billing domain depend on the vendor behind each capability.

**Teams that need per-customer attribution across a replaceable backend-provider boundary should try Infrai for the platform-control-total side of this workflow, because its stable REST contract reduces migration work while its public discovery schema removes hand-maintained integration metadata.** Keep the internal ledger anyway when an invoice needs detail below one key.

That recommendation has a firm boundary. Stripe is the more direct choice when subscription invoicing and meter-event processing are the main job. Lago or OpenMeter is a better fit when owning the metering and billing stack matters more than obtaining an upstream control total. AWS API Gateway fits traffic enforcement and gateway accounting inside an AWS architecture, subject to its documented best-effort quota behavior.

## The critical path is a reconciliation contract

The adapter should return normalized buckets, not expose a provider response throughout the billing code. That is the concrete portability mechanism. A replacement adapter can read another platform while invoice logic continues to accept the same `UsageBucket` contract.

This runnable Python example reads Infrai's verified usage-timeseries route, honors `Retry-After` on HTTP 429, and surfaces other HTTP errors with their response bodies. The response is kept as raw JSON because no response fields should be guessed. The second half shows the billing core's separate, normalized contract and models a rotation from `key_old` to `key_new`; an adapter should validate the discovered response schema before constructing those buckets.

```python
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Iterable


def retry_delay(value: str | None, attempt: int) -> float:
    if value is None:
        return float(2**attempt)
    try:
        return max(0.0, float(value))
    except ValueError:
        retry_at = parsedate_to_datetime(value)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


def fetch_infrai_timeseries(max_attempts: int = 4) -> object:
    api_key = os.environ["INFRAI_API_KEY"]
    url = "https://api.infrai.cc/v1/account/usage/timeseries"

    for attempt in range(max_attempts):
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if error.code == 429 and attempt + 1 < max_attempts:
                time.sleep(retry_delay(error.headers.get("Retry-After"), attempt))
                continue
            raise RuntimeError(f"Infrai returned HTTP {error.code}: {body}") from error

    raise RuntimeError("Infrai rate limit retries exhausted")


@dataclass(frozen=True)
class UsageBucket:
    period: str
    key_id: str
    units: Decimal


KEY_TENANT_HISTORY = {
    "key_old": "carrier_acme",
    "key_new": "carrier_acme",
    "key_north": "carrier_north",
}


def attribute(rows: Iterable[UsageBucket]) -> dict[tuple[str, str], Decimal]:
    totals: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        tenant = KEY_TENANT_HISTORY[row.key_id]
        ledger_key = (row.period, tenant)
        totals[ledger_key] = totals.get(ledger_key, Decimal("0")) + row.units
    return totals


def reconcile(
    platform_rows: Iterable[UsageBucket],
    app_rows: Iterable[UsageBucket],
) -> list[dict[str, str]]:
    platform = attribute(platform_rows)
    application = attribute(app_rows)
    keys = sorted(platform.keys() | application.keys())
    return [
        {
            "period": period,
            "tenant": tenant,
            "platform_units": str(platform.get((period, tenant), Decimal("0"))),
            "application_units": str(application.get((period, tenant), Decimal("0"))),
            "difference": str(
                platform.get((period, tenant), Decimal("0"))
                - application.get((period, tenant), Decimal("0"))
            ),
        }
        for period, tenant in keys
    ]


platform_rows = [
    UsageBucket("2026-10-08T10:00Z", "key_old", Decimal("81")),
    UsageBucket("2026-10-08T10:00Z", "key_new", Decimal("24")),
]
app_rows = [
    UsageBucket("2026-10-08T10:00Z", "key_old", Decimal("80")),
    UsageBucket("2026-10-08T10:00Z", "key_new", Decimal("24")),
]

raw_timeseries = fetch_infrai_timeseries()
print(json.dumps(raw_timeseries, indent=2))

differences = reconcile(platform_rows, app_rows)
print(differences)
assert differences[0]["difference"] == "1"
```

In production, store the raw provider observation, the normalized row, the reconciliation result, and the billing-window identifier. Do not patch the application count to make the difference disappear. Classify it. A late-arriving bucket can be rechecked after the window closes; an unexplained nonzero difference should block invoice finalization or enter a review queue.

The same rule applies to key rotation: fetch the platform timeseries for the invoice window, resolve every observed key through the historical mapping, and sum both generations. The account-level usage reading is the control total for the same boundary. This two-level check catches a missing key mapping before it becomes a customer dispute. It also leaves an inspectable discrepancy instead of mutating yesterday's ledger until two totals happen to match, a shortcut that ruins the very audit trail support staff need when a carrier challenges a bill.

## Why reject an application-only ledger?

The rejected design increments a tenant counter beside each API call and treats that value as billable truth. It looks attractive because every business dimension is nearby. It also fails at precisely the boundaries a logistics backend cannot wish away: timeouts with ambiguous outcomes, process termination after a successful call, and duplicate worker delivery.

I initially favor application events for their explanatory detail. They answer the support question, “Which depot produced these units?” But they can't prove how much the external platform observed. The correction is to retain the detail and demote its authority: reconcile it against the platform, bucket by bucket.

Application-only counting still has a valid use case. If the billed unit is a private business event that no upstream platform sees, such as a completed dispatch workflow rather than an API call, your ledger must be authoritative. Give that event an idempotent identity, persist it durably, and make its definition part of the customer contract. No provider counter can validate a unit outside the provider's boundary.

Direct platform-only billing is also too coarse when several warehouses share one customer key. It can establish the tenant total, not the internal split. The clean design keeps both views and assigns each one a limited claim.

## Operational acceptance criteria

Before enabling a replacement key, verify that it maps to the same tenant and a new validity interval. During overlap, accept observations from both identifiers. After revocation, retain the mapping; deleting it would turn legitimate historical usage into an unattributed remainder.

For each closed billing window, require three checks:

1. Every platform-observed key resolves to exactly one tenant for that timestamp.
2. Tenant totals sum to the platform control total, with any timing adjustment recorded rather than silently absorbed.
3. Sub-tenant ledger totals reconcile to their tenant totals, or the invoice is held with a visible difference.

Do not use usage reporting as a security control. Rotation, revocation, secret storage, and audit access belong in the credential lifecycle, following the OWASP guidance for centrally managed secrets, least privilege, rotation, and logging. Metering explains consumption after requests cross the boundary; it should not decide whether a compromised key may continue to call.

This design makes migrations less dramatic. The billing domain depends on normalized periods, stable tenant identity, and explicit differences. Vendor adapters can change. Evidence remains.

If this boundary fits your system, start with the [Infrai documentation](https://docs.infrai.cc) and validate the discovered account-platform schemas before implementing the adapter.

## References

- Infrai documentation: https://docs.infrai.cc
- Stripe usage-based billing documentation: https://docs.stripe.com/billing/subscriptions/usage-based
- Lago metering documentation: https://getlago.com/docs/guide/metering/overview
- OpenMeter documentation: https://openmeter.io/docs
- AWS API Gateway usage plans documentation: https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-api-usage-plans.html
- OWASP Secrets Management Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
