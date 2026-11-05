"""Make a customer's subscription renewal fail (or recover it), like a real expired card.

Fail:     swaps the subscription's card to Stripe's always-declining test card and bills
          the renewal now. The charge fails, Stripe marks the subscription past_due and
          sends invoice.payment_failed + customer.subscription.updated. HubSpot flips to
          At risk and stays there until the customer pays.
Recover:  puts a good test card back and pays the open invoice. Stripe sends invoice.paid
          and the subscription returns to active.

Usage:  python scripts/simulate_payment_failure.py                       (first sample customer)
        python scripts/simulate_payment_failure.py --email someone@x.example.com
        python scripts/simulate_payment_failure.py --recover
"""
import argparse

from stripe_common import as_dict, billing_contacts, find_customer, stripe


def live_subscription(customer_id):
    subs = as_dict(stripe.Subscription.list(customer=customer_id, status="all", limit=10))["data"]
    return next((s for s in subs if s["status"] in ("active", "trialing", "past_due", "unpaid")), None)


def fail(cust, sub) -> None:
    bad = as_dict(stripe.PaymentMethod.attach("pm_card_chargeCustomerFail", customer=cust["id"]))
    # Bill the renewal now with the declining card. allow_incomplete = don't raise; let it go past_due.
    updated = as_dict(stripe.Subscription.modify(
        sub["id"], default_payment_method=bad["id"], billing_cycle_anchor="now",
        proration_behavior="none", payment_behavior="allow_incomplete"))
    print(f"Renewal charge declined. Subscription is now: {updated['status']}")
    print("Watch the sync terminal: invoice.payment_failed -> at_risk, subscription.updated -> at_risk.")


def recover(cust, sub) -> None:
    good = as_dict(stripe.PaymentMethod.attach("pm_card_visa", customer=cust["id"]))
    stripe.Subscription.modify(sub["id"], default_payment_method=good["id"])
    stripe.Customer.modify(cust["id"], invoice_settings={"default_payment_method": good["id"]})
    open_invoices = as_dict(stripe.Invoice.list(customer=cust["id"], status="open", limit=10))["data"]
    for inv in open_invoices:
        stripe.Invoice.pay(inv["id"], payment_method=good["id"])
        print(f"Paid open invoice {inv['id']}")
    status = as_dict(stripe.Subscription.retrieve(sub["id"]))["status"]
    print(f"Subscription is now: {status}. HubSpot should return to Active.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", help="customer email (defaults to the first sample billing contact)")
    parser.add_argument("--recover", action="store_true", help="fix the card and pay what's owed")
    args = parser.parse_args()

    email = args.email or billing_contacts()[0][0]["email"]
    cust = find_customer(email)
    if not cust:
        raise SystemExit(f"No Stripe customer with email {email}. Run seed_stripe.py first.")
    sub = live_subscription(cust["id"])
    if not sub:
        raise SystemExit(f"{email} has no active subscription.")

    print(f"{'Recovering' if args.recover else 'Failing renewal for'} {email} ({sub['id']}, now {sub['status']})")
    recover(cust, sub) if args.recover else fail(cust, sub)


if __name__ == "__main__":
    main()
