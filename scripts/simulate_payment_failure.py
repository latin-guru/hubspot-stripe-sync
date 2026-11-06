"""Make a customer's payment fail (or recover it), to demo the at-risk flow.

Fail:     switches the customer to Stripe's always-declining test card (so future renewals
          fail too) and charges an invoice the card must pay. Any account credit (e.g. from
          downgrade prorations) is added to the amount so the card is really charged.
          Stripe sends invoice.payment_failed and HubSpot flips to At risk.
Recover:  puts a good test card back and pays anything still open; Stripe sends invoice.paid.

Usage:  python scripts/simulate_payment_failure.py
        python scripts/simulate_payment_failure.py --email someone@x.example.com
        python scripts/simulate_payment_failure.py --recover
"""
import argparse

from stripe_common import as_dict, billing_contacts, find_customer, stripe


def live_subscription(customer_id):
    subs = as_dict(stripe.Subscription.list(customer=customer_id, status="all", limit=10))["data"]
    return next((s for s in subs if s["status"] in ("active", "trialing", "past_due", "unpaid")), None)


def fail(cust, sub):
    bad = as_dict(stripe.PaymentMethod.attach("pm_card_chargeCustomerFail", customer=cust["id"]))["id"]
    stripe.Customer.modify(cust["id"], invoice_settings={"default_payment_method": bad})
    stripe.Subscription.modify(sub["id"], default_payment_method=bad)

    credit = max(0, -(as_dict(stripe.Customer.retrieve(cust["id"])).get("balance") or 0))
    stripe.InvoiceItem.create(customer=cust["id"], amount=4900 + credit, currency="usd",
                              description="Monthly usage (simulated failed payment)")
    inv = as_dict(stripe.Invoice.create(
        customer=cust["id"], collection_method="charge_automatically",
        pending_invoice_items_behavior="include", default_payment_method=bad, auto_advance=False))
    inv = as_dict(stripe.Invoice.finalize_invoice(inv["id"]))
    if inv["status"] == "paid":
        raise SystemExit("Invoice was covered by account credit; run the script again.")
    try:
        stripe.Invoice.pay(inv["id"])
        print("Unexpected: payment succeeded.")
    except stripe.error.CardError:
        print(f"Card declined on ${inv['amount_due'] / 100:.2f}. Invoice {inv['id']} left open until --recover.")
        print("Watch the sync terminal for 'payment FAILED, at_risk'.")


def recover(cust, sub):
    good = as_dict(stripe.PaymentMethod.attach("pm_card_visa", customer=cust["id"]))["id"]
    stripe.Customer.modify(cust["id"], invoice_settings={"default_payment_method": good})
    stripe.Subscription.modify(sub["id"], default_payment_method=good)
    for inv in as_dict(stripe.Invoice.list(customer=cust["id"], status="open", limit=10))["data"]:
        stripe.Invoice.pay(inv["id"], payment_method=good)
        print(f"Paid open invoice {inv['id']}")
    print("Recovered. HubSpot should return to Active.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email")
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    email = args.email or billing_contacts()[0][0]["email"]
    cust = find_customer(email)
    if not cust:
        raise SystemExit(f"No Stripe customer with email {email}. Run seed_stripe.py first.")
    sub = live_subscription(cust["id"])
    if not sub:
        raise SystemExit(f"{email} has no active subscription.")
    print(f"{'Recovering' if args.recover else 'Failing payment for'} {email} ({sub['id']}, now {sub['status']})")
    recover(cust, sub) if args.recover else fail(cust, sub)


if __name__ == "__main__":
    main()
