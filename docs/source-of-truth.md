# Field mapping and source-of-truth rules

Each field has exactly one owner. The owner's value wins; the other system only reads it.

| HubSpot property | Objects | Type | Owner | Stripe source | Written by |
|---|---|---|---|---|---|
| `stripe_customer_id` | Contact, Company | Text | Stripe | `customer.id` | `customer.created` |
| `billing_status` | Contact, Company | Dropdown (active, trialing, at_risk, canceled) | Stripe | `subscription.status`, `invoice.payment_failed` | subscription + invoice events |
| `mrr` | Contact, Company | Number (currency) | Stripe | subscription item price × quantity | `customer.subscription.updated`, `invoice.paid` |
| `last_payment_date` | Contact, Company | Date | Stripe | `invoice.status_transitions.paid_at` | `invoice.paid` |
| `plan_tier` | Contact, Company | Dropdown (starter, growth, scale) | **Shared, see rule 3** | price metadata `plan_tier` | both directions |
| `lifecyclestage` | Contact, Company | Standard | HubSpot | none | HubSpot workflows |
| `hubspot_owner_id` | Contact, Company, Deal | Standard | HubSpot | none | HubSpot |
| `sync_source` | Contact, Company | Text | Integration | none | the sync service on every write |

## Rules

1. **Stripe owns money.** Anything about billing (status, MRR, payment dates, customer ID) is written only by the Stripe → HubSpot sync. Users should treat these as read-only in HubSpot.
2. **HubSpot owns the relationship.** Lifecycle stage, owner, and deal stage are never written from Stripe.
3. **Plan tier is the one two-way field.** A sales rep can change `plan_tier` in HubSpot (an upgrade or downgrade), which updates Stripe. Stripe then confirms it back. The last confirmed Stripe value is the final word.
4. **Loop guard.** Every write by the sync stamps `sync_source` (`stripe` or `hubspot`). Changes stamped by the integration itself are ignored by the opposite direction, so the systems never ping-pong.
5. **Matching key.** Contacts are matched by email; companies by domain. After the first sync, `stripe_customer_id` is the stable link.
6. **Idempotency.** Stripe event IDs are stored once processed; a repeated or out-of-order event is skipped.
