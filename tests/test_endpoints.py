"""End-to-end through the FastAPI app with signed Stripe events and HubSpot calls."""
from app import config, main
from conftest import event, subscription


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


# ---------- Stripe -> HubSpot ----------

def test_bad_signature_is_rejected(send_stripe, hubspot):
    resp = send_stripe(event("evt_1", "invoice.paid", {"customer": "cus_1"}), secret="whsec_wrong")
    assert resp.status_code == 400
    assert hubspot.calls == []


def test_missing_signature_is_rejected(client):
    assert client.post("/webhooks/stripe", content="{}").status_code == 400


def test_event_applied_once_then_duplicate(send_stripe, hubspot):
    evt = event("evt_1", "invoice.payment_failed", {"customer": "cus_1"})
    assert send_stripe(evt).json()["status"] == "applied"
    assert send_stripe(evt).json()["status"] == "duplicate"
    assert len(hubspot.of("upsert_contact")) == 1


def test_older_event_for_same_subscription_is_stale(send_stripe, hubspot):
    send_stripe(event("evt_new", "customer.subscription.updated", subscription("scale"), created=200))
    resp = send_stripe(event("evt_old", "customer.subscription.updated", subscription("growth"), created=100))
    assert resp.json()["status"] == "stale"
    assert hubspot.of("upsert_contact")[-1][2]["plan_tier"] == "scale"


def test_late_invoice_paid_cannot_undo_newer_failure(send_stripe, hubspot):
    send_stripe(event("evt_fail", "invoice.payment_failed", {"customer": "cus_1"}, created=300))
    resp = send_stripe(event("evt_paid", "invoice.paid", {"customer": "cus_1"}, created=250))
    assert resp.json()["status"] == "stale"
    assert hubspot.of("upsert_contact")[-1][2]["billing_status"] == "at_risk"


def test_unrelated_events_do_not_block_each_other(send_stripe):
    a = send_stripe(event("evt_a", "invoice.paid", {"customer": "cus_1"}, created=500))
    b = send_stripe(event("evt_b", "customer.subscription.created", subscription(), created=400))
    assert a.json()["status"] == b.json()["status"] == "applied"


def test_unhandled_event_type_is_ignored(send_stripe, hubspot):
    resp = send_stripe(event("evt_1", "charge.succeeded", {"id": "ch_1"}))
    assert resp.json() == {"status": "ignored", "type": "charge.succeeded"}
    assert hubspot.calls == []


def test_processing_error_returns_500_and_stripe_can_retry(send_stripe, hubspot, monkeypatch):
    real = hubspot.upsert_contact
    failures = [RuntimeError("HubSpot down")]

    def fail_once(*a, **k):
        if failures:
            raise failures.pop()
        return real(*a, **k)
    monkeypatch.setattr(hubspot, "upsert_contact", fail_once)
    evt = event("evt_1", "invoice.paid", {"customer": "cus_1"})
    assert send_stripe(evt).status_code == 500
    # not marked as processed, so Stripe's retry is applied
    assert send_stripe(evt).json()["status"] == "applied"


# ---------- HubSpot -> Stripe ----------

def test_hubspot_wrong_or_missing_secret(send_hubspot, stripe_fake):
    assert send_hubspot({"objectId": 101}, secret="nope").status_code == 401
    assert send_hubspot({"objectId": 101}, secret=None).status_code == 401
    assert stripe_fake.modified == []


def test_hubspot_rejected_when_no_secret_configured(send_hubspot, monkeypatch):
    monkeypatch.setattr(config, "HUBSPOT_WEBHOOK_SECRET", "")
    assert send_hubspot({"objectId": 101}, secret="").status_code == 401


def test_hubspot_bad_json(client):
    resp = client.post("/webhooks/hubspot", content="not json",
                       headers={"X-Sync-Secret": config.HUBSPOT_WEBHOOK_SECRET})
    assert resp.status_code == 400


def test_hubspot_payload_without_contact_id(send_hubspot):
    assert send_hubspot({"foo": 1}).status_code == 400
    assert send_hubspot(["x"]).status_code == 400


def test_hubspot_plan_change_pushes_then_loop_guard(send_hubspot, hubspot, stripe_fake):
    hubspot.contacts["101"]["plan_tier"] = "scale"
    assert "pushed to Stripe" in send_hubspot({"objectId": 101}).json()["result"]
    assert "loop guard" in send_hubspot({"objectId": 101}).json()["result"]
    assert len(stripe_fake.modified) == 1


def test_hubspot_skip_is_ok(send_hubspot):
    assert send_hubspot({"objectId": 999}).json()["result"].startswith("skipped")


def test_hubspot_processing_error_returns_500(send_hubspot, hubspot, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(hubspot, "get_contact", boom)
    assert send_hubspot({"objectId": 101}).status_code == 500


# ---------- startup ----------

def test_get_state_builds_real_clients(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setattr(config, "HUBSPOT_SERVICE_KEY", "test-key")
    main.state.clear()
    try:
        s = main.get_state()
        assert set(s) == {"store", "sync", "push"}
        assert main.get_state() is s
    finally:
        main.state.clear()
