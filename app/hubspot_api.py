"""HubSpot operations the sync needs, built on the retrying client."""
from typing import Optional

from .hubspot_client import HubSpotClient, HubSpotError


class HubSpotAPI:
    def __init__(self, client: HubSpotClient):
        self.hs = client

    def _ok(self, resp, what):
        if resp.status_code >= 300:
            raise HubSpotError(f"{what} failed: {resp.status_code} {resp.text}")
        return resp.json() if resp.content else {}

    def upsert_contact(self, email: str, properties: dict) -> str:
        body = {"inputs": [{"idProperty": "email", "id": email,
                            "properties": {"email": email, **properties}}]}
        data = self._ok(self.hs.post("/crm/v3/objects/contacts/batch/upsert", json=body), "contact upsert")
        return data["results"][0]["id"]

    def _search_one(self, obj: str, prop: str, value: str, props=None) -> Optional[dict]:
        body = {"filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}],
                "properties": props or [prop], "limit": 1}
        results = self._ok(self.hs.post(f"/crm/v3/objects/{obj}/search", json=body), f"{obj} search").get("results", [])
        return results[0] if results else None

    def find_company_by_domain(self, domain: str) -> Optional[str]:
        hit = self._search_one("companies", "domain", domain)
        return hit["id"] if hit else None

    def find_deal_by_subscription(self, subscription_id: str) -> Optional[str]:
        hit = self._search_one("deals", "stripe_subscription_id", subscription_id)
        return hit["id"] if hit else None

    def get_contact(self, contact_id: str, properties) -> Optional[dict]:
        resp = self.hs.get(f"/crm/v3/objects/contacts/{contact_id}",
                           params={"properties": ",".join(properties)})
        if resp.status_code == 404:
            return None
        return self._ok(resp, "contact get")

    def find_contact_by_email(self, email: str) -> Optional[dict]:
        return self._search_one("contacts", "email", email, props=["email", "plan_tier", "stripe_customer_id"])

    def update(self, obj: str, record_id: str, properties: dict) -> None:
        self._ok(self.hs.patch(f"/crm/v3/objects/{obj}/{record_id}", json={"properties": properties}),
                 f"{obj} update")

    def create_deal(self, properties: dict) -> str:
        return self._ok(self.hs.post("/crm/v3/objects/deals", json={"properties": properties}),
                        "deal create")["id"]

    def associate(self, from_obj: str, from_id: str, to_obj: str, to_id: str) -> None:
        """Default (unlabeled) association. Safe to repeat."""
        self._ok(self.hs.request(
            "PUT", f"/crm/v4/objects/{from_obj}/{from_id}/associations/default/{to_obj}/{to_id}"),
            f"associate {from_obj}->{to_obj}")
