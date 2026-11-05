import pytest

from app.stripe_push import HubSpotToStripe, extract_contact_id


def push(hubspot, stripe_fake):
    return HubSpotToStripe(hubspot, stripe_fake)


def test_plan_change_switches_stripe_price(hubspot, stripe_fake):
    hubspot.contacts["101"]["plan_tier"] = "scale"
    result = push(hubspot, stripe_fake).plan_changed("101")
    assert result.endswith("growth -> scale pushed to Stripe (sub_1)")
    sub_id, kwargs = stripe_fake.modified[0]
    assert kwargs["items"] == [{"id": "si_1", "price": "price_scale"}]
    assert kwargs["proration_behavior"] == "create_prorations"
    assert kwargs["metadata"]["last_plan_change_source"] == "hubspot"


def test_loop_guard_skips_when_stripe_already_matches(hubspot, stripe_fake):
    result = push(hubspot, stripe_fake).plan_changed("101")      # both say growth
    assert "nothing to do (loop guard)" in result
    assert stripe_fake.modified == []


def test_round_trip_changes_stripe_once(hubspot, stripe_fake):
    p = push(hubspot, stripe_fake)
    hubspot.contacts["101"]["plan_tier"] = "starter"
    p.plan_changed("101")
    p.plan_changed("101")   # workflow fires again after Stripe's echo is written back
    assert len(stripe_fake.modified) == 1


@pytest.mark.parametrize("change,expected", [
    ({"plan_tier": "platinum"}, "no valid plan tier"),
    ({"plan_tier": ""}, "no valid plan tier (blank)"),
    ({"stripe_customer_id": None}, "not linked to a Stripe customer"),
])
def test_invalid_contacts_are_skipped(hubspot, stripe_fake, change, expected):
    hubspot.contacts["101"].update(change)
    assert expected in push(hubspot, stripe_fake).plan_changed("101")
    assert stripe_fake.modified == []


def test_unknown_contact(hubspot, stripe_fake):
    assert "not found" in push(hubspot, stripe_fake).plan_changed("999")


def test_no_live_subscription(hubspot, stripe_fake):
    stripe_fake.subs["cus_1"][0]["status"] = "canceled"
    hubspot.contacts["101"]["plan_tier"] = "scale"
    assert "no active subscription" in push(hubspot, stripe_fake).plan_changed("101")


def test_missing_price_raises(hubspot, stripe_fake):
    with pytest.raises(RuntimeError, match="No Stripe price"):
        push(hubspot, stripe_fake).price_for("enterprise")


def test_price_lookup_is_cached(hubspot, stripe_fake):
    p = push(hubspot, stripe_fake)
    assert p.price_for("scale") == "price_scale"
    stripe_fake.Price = None   # would explode if called again
    assert p.price_for("scale") == "price_scale"


@pytest.mark.parametrize("body,expected", [
    ({"objectId": 101}, "101"),
    ({"contactId": "102"}, "102"),
    ({"hs_object_id": {"value": "103"}}, "103"),
    ({"properties": {"hs_object_id": {"value": "104"}}}, "104"),
    ({"properties": {"hs_object_id": "105"}}, "105"),
    ([{"objectId": 106}], "106"),
    ({"foo": 1}, None),
    ({"properties": {"other": 1}}, None),
    ([], None),
    ("text", None),
])
def test_extract_contact_id_shapes(body, expected):
    assert extract_contact_id(body) == expected
