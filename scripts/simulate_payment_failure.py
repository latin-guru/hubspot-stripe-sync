"""Make one customer's payment fail, to demo the at-risk flow.

Attaches Stripe's test card that always declines (pm_card_chargeCustomerFail) and
charges a small one-off invoice. Stripe sends invoice.payment_failed and the sync
service flips the contact and company to billing_status = at_risk.

Usage:  python scripts/simulate_payment_failure.py                    (first sample customer)
        python scripts/simulate_payment_failure.py --email someone@x.example.com
"""
import argparse

from stripe_common import as_dict, billing_contacts, find_customer, stripe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", help="customer email (defaults to the first sample billing contact)")
    args = parser.parse_args()

    email = args.email or billing_contacts()[0][0]["email"]
    cust = find_customer(email)
    if not cust:
        raise SystemExit(f"No Stripe customer with email {email}. Run seed_stripe.py first.")

    pm = as_dict(stripe.PaymentMethod.attach("pm_card_chargeCustomerFail", customer=cust["id"]))
    stripe.InvoiceItem.create(customer=cust["id"], amount=4900, currency="usd",
                              description="Usage overage (simulated failure)")
    invoice = as_dict(stripe.Invoice.create(
        customer=cust["id"], collection_method="charge_automatically",
        pending_invoice_items_behavior="include", default_payment_method=pm["id"], auto_advance=False))
    stripe.Invoice.finalize_invoice(invoice["id"])
    try:
        stripe.Invoice.pay(invoice["id"])
        print("Unexpected: payment succeeded.")
    except Exception as exc:  # the decline is the point
        print(f"Payment declined as planned for {email}: {getattr(exc, 'user_message', None) or exc}")
        print("Watch the sync terminal for 'payment FAILED, at_risk', then check the contact in HubSpot.")


if __name__ == "__main__":
    main()
