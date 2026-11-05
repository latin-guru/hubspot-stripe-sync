from app.handlers import StripeToHubSpot, ordering_key
from conftest import EMAIL, subscription


def sync(hubspot, store, stripe_fake):
    return StripeToHubSpot(hubspot, store, stripe_fake)


def test_customer_created_links_contact_and_company(hubspot, store, stripe_fake):
    result = sync(hubspot, store, stripe_fake).customer_created({"id": "cus_1", "email": EMAIL})
    assert "contact 101, company 201" in result
    _, email, props = hubspot.of("upsert_contact")[0]
    assert props == {"stripe_customer_id": "cus_1", "sync_source": "stripe"}
    assert ("associate", "contacts", "101", "companies", "201") in hubspot.calls


def test_customer_without_company(hubspot, store, stripe_fake):
    result = sync(hubspot, store, stripe_fake).customer_created({"id": "cus_9", "email": "x@gmail.com"})
    assert "company none" in result
    assert not hubspot.of("associate")


def test_customer_without_email_is_skipped(hubspot, store, stripe_fake):
    assert sync(hubspot, store, stripe_fake).customer_created({"id": "cus_1"}).startswith("skipped")
    assert hubspot.calls == []


def test_new_subscription_creates_one_closed_won_deal(hubspot, store, stripe_fake):
    s = sync(hubspot, store, stripe_fake)
    assert "created deal d1" in s.subscription_changed(subscription("growth"))
    deal = hubspot.of("create_deal")[0][1]
    assert deal["amount"] == 3588.0 and deal["dealstage"] == "closedwon"
    assert deal["dealname"] == "Acme - Growth plan"
    assert ("associate", "deals", "d1", "contacts", "101") in hubspot.calls
    assert ("associate", "deals", "d1", "companies", "201") in hubspot.calls
    contact_props = hubspot.of("upsert_contact")[0][2]
    assert contact_props["plan_tier"] == "growth" and contact_props["mrr"] == 299.0
    # billing fields only: lifecycle and owner belong to HubSpot
    assert "lifecyclestage" not in contact_props and "hubspot_owner_id" not in contact_props


def test_plan_change_updates_same_deal_even_when_search_lags(hubspot, store, stripe_fake):
    s = sync(hubspot, store, stripe_fake)
    s.subscription_changed(subscription("growth"))
    hubspot.search_lag = True          # HubSpot search hasn't indexed the new deal yet
    assert "updated deal d1" in s.subscription_changed(subscription("scale"))
    assert len(hubspot.of("create_deal")) == 1
    assert ("update", "deals", "d1", {"amount": 9588.0}) in hubspot.calls


def test_existing_deal_found_by_search(hubspot, store, stripe_fake):
    hubspot.deals_by_sub["sub_1"] = "d77"
    assert "updated deal d77" in sync(hubspot, store, stripe_fake).subscription_changed(subscription())


def test_past_due_subscription_is_at_risk(hubspot, store, stripe_fake):
    sync(hubspot, store, stripe_fake).subscription_changed(subscription(status="past_due"))
    assert hubspot.of("upsert_contact")[0][2]["billing_status"] == "at_risk"


def test_canceled_subscription_zeroes_mrr_and_creates_no_deal(hubspot, store, stripe_fake):
    result = sync(hubspot, store, stripe_fake).subscription_changed(subscription(status="canceled"))
    assert "no deal (canceled)" in result
    assert hubspot.of("upsert_contact")[0][2]["mrr"] == 0.0
    assert not hubspot.of("create_deal")


def test_subscription_for_deleted_customer_is_skipped(hubspot, store, stripe_fake):
    sub = subscription(customer="cus_gone")
    assert sync(hubspot, store, stripe_fake).subscription_changed(sub).startswith("skipped")


def test_invoice_paid_sets_active_and_date(hubspot, store, stripe_fake):
    inv = {"customer": "cus_1", "status_transitions": {"paid_at": 1762300800}}
    assert "paid 2025-11-05, active" in sync(hubspot, store, stripe_fake).invoice_paid(inv)
    props = hubspot.of("upsert_contact")[0][2]
    assert props["billing_status"] == "active" and props["last_payment_date"] == "2025-11-05"


def test_invoice_paid_falls_back_to_created(hubspot, store, stripe_fake):
    sync(hubspot, store, stripe_fake).invoice_paid({"customer": "cus_1", "created": 1762300800})
    assert hubspot.of("upsert_contact")[0][2]["last_payment_date"] == "2025-11-05"


def test_payment_failed_sets_at_risk(hubspot, store, stripe_fake):
    assert "FAILED" in sync(hubspot, store, stripe_fake).invoice_payment_failed({"customer": "cus_1"})
    assert hubspot.of("upsert_contact")[0][2]["billing_status"] == "at_risk"
    assert ("update", "companies", "201", {"stripe_customer_id": "cus_1", "billing_status": "at_risk",
                                           "sync_source": "stripe"}) in hubspot.calls


def test_invoice_events_for_unknown_customer_are_skipped(hubspot, store, stripe_fake):
    s = sync(hubspot, store, stripe_fake)
    assert s.invoice_paid({"customer": "cus_x"}).startswith("skipped")
    assert s.invoice_payment_failed({"customer": "cus_x"}).startswith("skipped")


def test_routes_cover_the_six_events(hubspot, store, stripe_fake):
    assert len(sync(hubspot, store, stripe_fake).routes()) == 6


def test_ordering_keys():
    assert ordering_key("customer.subscription.updated", {"id": "sub_1"}) == "sub:sub_1"
    assert ordering_key("invoice.paid", {"customer": "cus_1"}) == "payments:cus_1"
    assert ordering_key("customer.created", {"object": "customer", "id": "cus_1"}) == "customer:cus_1"
