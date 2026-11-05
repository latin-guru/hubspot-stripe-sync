# HubSpot ↔ Stripe Billing Sync

**Public showcase.** Sales can't see billing status in the CRM, so reps call customers whose card just failed without knowing it. This project keeps HubSpot and Stripe in step: Stripe billing events update HubSpot records, deals and tasks, and plan changes made in HubSpot flow back to Stripe.

Fictional company: **Northwind Loop**, a B2B SaaS selling Starter / Growth / Scale plans. All data is fake (Faker, Stripe test mode, HubSpot developer test account).

> Status: Phases 1–2 complete (data model, Stripe → HubSpot sync). Phases 3–4 in progress. Items not built yet are marked *Roadmap*.

## Architecture
![Architecture](docs/architecture.png)

## Data model
- Custom property group **Billing (synced from Stripe)** on Contact and Company: `plan_tier`, `mrr`, `billing_status`, `stripe_customer_id`, `last_payment_date`, `sync_source`.
- Field ownership rules: [docs/source-of-truth.md](docs/source-of-truth.md)

![Billing properties in HubSpot](docs/screenshots/properties.png)
![Contact record associated to its company](docs/screenshots/contact-record.png)

## Setup
1. `python -m venv .venv` and activate it, then `pip install -r requirements.txt`
2. `cp .env.example .env` and add a HubSpot **Service Key** (HubSpot stopped allowing new legacy private apps on Oct 26, 2026, so this project uses Service Keys).
3. `python scripts/generate_sample_data.py`
4. `python scripts/create_properties.py`
5. `python scripts/import_sample_data.py` (`scripts/reset_sample_data.py` archives the sample records if you want a clean reload)

## Sample data
30 fictional companies on reserved `example.com` subdomains with one or two contacts each, generated with a fixed seed so results are reproducible.

## Roadmap
- HubSpot → Stripe plan sync with loop guard
- Payment-failed workflow, revenue dashboard, pytest + GitHub Actions

## Contact
[LinkedIn: Kevin Gaviria](https://www.linkedin.com/in/kevin-gaviria)

## Phase 2: Stripe → HubSpot sync
A FastAPI service receives Stripe webhooks and keeps HubSpot current. Stripe owns the billing fields; HubSpot keeps lifecycle and owner.

| Stripe event | HubSpot result |
|---|---|
| `customer.created` | Contact linked by email, company by domain, `stripe_customer_id` set |
| `customer.subscription.*` | Plan tier, MRR, billing status set; closed-won deal created once per subscription |
| `invoice.paid` | Billing status Active, last payment date set |
| `invoice.payment_failed` | Billing status **At risk** |

**Reliability**
- Webhook signature verified on every request; unsigned calls are rejected
- Idempotent: each Stripe event ID is applied once, so retries and duplicates are skipped
- Order-safe: an older event for the same subscription can't overwrite newer data
- HubSpot 429/5xx retried with backoff (honors `Retry-After`); failures return 500 so Stripe retries
- Helper scripts refuse to run with a live Stripe key

**Run it locally** (three terminals)
1. `stripe listen --events customer.created,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,invoice.paid,invoice.payment_failed --forward-to localhost:8000/webhooks/stripe`
2. `uvicorn app.main:app --port 8000`
3. `python scripts/seed_stripe.py` then `python scripts/simulate_payment_failure.py`

**After the sync** (contact record, billing fields filled by Stripe):
![Billing fields synced from Stripe](docs/screenshots/billing-synced.png)

**Payment failure** flips the contact to At risk:
![Contact at risk after a failed payment](docs/screenshots/at-risk.png)

**Timeline**: deal created and closed-won by the integration; HubSpot then promotes the contact to Customer on its own:
![Sync activity timeline](docs/screenshots/sync-timeline.png)
