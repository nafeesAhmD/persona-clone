from app.billing.providers.base import BillingProvider


class StripeProvider(BillingProvider):
    def __init__(self, secret_key: str | None = None, webhook_secret: str | None = None):
        self.secret_key = secret_key
        self.webhook_secret = webhook_secret

    def create_customer(self, email: str, name: str | None = None) -> dict:
        return {"customer_id": None}

    def create_checkout_session(self, customer_id: str, price_id: str, success_url: str, cancel_url: str) -> dict:
        return {"url": None}

    def cancel_subscription(self, subscription_id: str) -> dict:
        return {"status": "cancelled"}

    def retrieve_subscription(self, subscription_id: str) -> dict:
        return {"status": "active"}

    def verify_webhook(self, payload: bytes, signature: str | None) -> dict:
        return {"type": "test", "data": {}}
