"""HTTP layer: retries, backoff, Retry-After, dropped connections, and the API wrapper."""
import pytest
import requests

from app import hubspot_client
from app.hubspot_api import HubSpotAPI
from app.hubspot_client import HubSpotClient, HubSpotError


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = str(self._body)
        self.content = b"x" if body is not None else b""

    def json(self):
        return self._body


@pytest.fixture
def no_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(hubspot_client.time, "sleep", waits.append)
    return waits


def client_with(responses):
    c = HubSpotClient(token="t", max_retries=3)
    seq = iter(responses)

    def fake(method, url, **kw):
        nxt = next(seq)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
    c.session.request = fake
    return c


def test_requires_token(monkeypatch):
    monkeypatch.delenv("HUBSPOT_SERVICE_KEY", raising=False)
    with pytest.raises(HubSpotError, match="not set"):
        HubSpotClient(token=None)


def test_sets_bearer_header():
    assert HubSpotClient(token="abc").session.headers["Authorization"] == "Bearer abc"


def test_429_honors_retry_after(no_sleep):
    c = client_with([Resp(429, headers={"Retry-After": "7"}), Resp(200, {})])
    assert c.get("/x").status_code == 200
    assert no_sleep == [7.0]


def test_5xx_exponential_backoff(no_sleep):
    c = client_with([Resp(502), Resp(503), Resp(200, {})])
    assert c.post("/x").status_code == 200
    assert no_sleep == [1, 2]


def test_gives_up_after_max_retries(no_sleep):
    c = client_with([Resp(500)] * 4)
    with pytest.raises(HubSpotError, match="failed after retries: 500"):
        c.patch("/x")


def test_dropped_connection_is_retried(no_sleep):
    c = client_with([requests.ConnectionError("reset by peer"), requests.Timeout("slow"), Resp(200, {})])
    assert c.get("/x").status_code == 200
    assert no_sleep == [1, 2]


def test_dropped_connection_gives_up(no_sleep):
    c = client_with([requests.ConnectionError("reset")] * 4)
    with pytest.raises(HubSpotError, match="reset"):
        c.get("/x")


def test_4xx_is_returned_not_retried(no_sleep):
    c = client_with([Resp(404)])
    assert c.get("/x").status_code == 404
    assert no_sleep == []


# ---------- API wrapper ----------

class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def _next(self, method, path, kw):
        self.sent.append((method, path, kw))
        return self.responses.pop(0)

    def request(self, method, path, **kw):
        return self._next(method, path, kw)

    def get(self, path, **kw):
        return self._next("GET", path, kw)

    def post(self, path, **kw):
        return self._next("POST", path, kw)

    def patch(self, path, **kw):
        return self._next("PATCH", path, kw)


def test_upsert_contact_by_email():
    fc = FakeClient([Resp(200, {"results": [{"id": "55"}]})])
    assert HubSpotAPI(fc).upsert_contact("a@b.com", {"mrr": 1}) == "55"
    body = fc.sent[0][2]["json"]["inputs"][0]
    assert body["idProperty"] == "email" and body["properties"] == {"email": "a@b.com", "mrr": 1}


def test_searches_return_id_or_none():
    api = HubSpotAPI(FakeClient([Resp(200, {"results": [{"id": "9"}]}), Resp(200, {"results": []}),
                                 Resp(200, {"results": [{"id": "d1"}]}),
                                 Resp(200, {"results": [{"id": "c1", "properties": {}}]})]))
    assert api.find_company_by_domain("x.com") == "9"
    assert api.find_company_by_domain("y.com") is None
    assert api.find_deal_by_subscription("sub_1") == "d1"
    assert api.find_contact_by_email("a@b.com")["id"] == "c1"


def test_get_contact_404_is_none():
    api = HubSpotAPI(FakeClient([Resp(404), Resp(200, {"id": "1", "properties": {}})]))
    assert api.get_contact("1", ["email"]) is None
    assert api.get_contact("1", ["email", "plan_tier"])["id"] == "1"


def test_update_create_associate():
    fc = FakeClient([Resp(200, {}), Resp(201, {"id": "d9"}), Resp(200, None)])
    api = HubSpotAPI(fc)
    api.update("deals", "1", {"amount": 5})
    assert api.create_deal({"dealname": "x"}) == "d9"
    api.associate("deals", "d9", "contacts", "1")
    assert fc.sent[2][:2] == ("PUT", "/crm/v4/objects/deals/d9/associations/default/contacts/1")


def test_errors_raise_with_context():
    api = HubSpotAPI(FakeClient([Resp(400, {"message": "bad property"})]))
    with pytest.raises(HubSpotError, match="deal create failed: 400"):
        api.create_deal({})
