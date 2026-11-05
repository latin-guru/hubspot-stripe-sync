import pytest

from app import mapping
from conftest import subscription


@pytest.mark.parametrize("stripe_status,expected", [
    ("active", "active"), ("trialing", "trialing"), ("past_due", "at_risk"), ("unpaid", "at_risk"),
    ("canceled", "canceled"), ("incomplete_expired", "canceled"), ("something_new", "at_risk"),
])
def test_billing_status_mapping(stripe_status, expected):
    assert mapping.billing_status(stripe_status) == expected


@pytest.mark.parametrize("interval,count,qty,expected", [
    ("month", 1, 1, 299.0),
    ("year", 1, 1, 24.92),     # annual price normalized to monthly
    ("month", 3, 1, 99.67),    # quarterly
    ("month", 1, 2, 598.0),    # quantity
    ("week", 1, 1, 1295.67),
])
def test_monthly_amount_normalizes(interval, count, qty, expected):
    price = {"unit_amount": 29900, "recurring": {"interval": interval, "interval_count": count}}
    assert mapping.monthly_amount(price, qty) == expected


def test_monthly_amount_handles_missing_fields():
    assert mapping.monthly_amount({}) == 0.0


def test_plan_and_mrr_from_metadata():
    assert mapping.plan_and_mrr(subscription("scale")) == ("scale", 799.0)


def test_plan_falls_back_to_lookup_key():
    sub = subscription("starter")
    sub["items"]["data"][0]["price"]["metadata"] = {}
    assert mapping.plan_and_mrr(sub) == ("starter", 99.0)


def test_unknown_plan_is_none_but_mrr_still_counts():
    sub = subscription("growth")
    sub["items"]["data"][0]["price"].update(metadata={"plan_tier": "platinum"}, lookup_key="other")
    assert mapping.plan_and_mrr(sub) == (None, 299.0)


def test_plan_and_mrr_empty_subscription():
    assert mapping.plan_and_mrr({}) == (None, 0.0)


def test_to_hs_date():
    assert mapping.to_hs_date(1762300800) == "2025-11-05"
    assert mapping.to_hs_date(None) is None


def test_email_domain():
    assert mapping.email_domain("A@Acme.Example.com") == "acme.example.com"
    assert mapping.email_domain("not-an-email") == ""
    assert mapping.email_domain("") == ""


def test_as_dict_variants():
    class WithToDict:
        def to_dict(self):
            return {"a": 1}

    class Mapping(dict):
        pass

    assert mapping.as_dict({"x": 1}) == {"x": 1}
    assert mapping.as_dict(WithToDict()) == {"a": 1}
    assert mapping.as_dict(Mapping(b=2)) == {"b": 2}
    assert mapping.as_dict([("c", 3)]) == {"c": 3}
