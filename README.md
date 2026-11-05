# HubSpot ↔ Stripe Billing Sync

**Public showcase.** Sales can't see billing status in the CRM, so reps call customers whose card just failed without knowing it. This project keeps HubSpot and Stripe in step: Stripe billing events update HubSpot records, deals and tasks, and plan changes made in HubSpot flow back to Stripe.

Fictional company: **Northwind Loop**, a B2B SaaS selling Starter / Growth / Scale plans. All data is fake (Faker, Stripe test mode, HubSpot developer test account).

> Status: Phase 1 (data model) complete. Phases 2–4 in progress. Items not built yet are marked *Roadmap*.

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
- Stripe → HubSpot webhook service (signature check, idempotency, 429 backoff)
- HubSpot → Stripe plan sync with loop guard
- Payment-failed workflow, revenue dashboard, pytest + GitHub Actions

## Contact
[LinkedIn: Kevin Gaviria](https://www.linkedin.com/in/kevin-gaviria)
