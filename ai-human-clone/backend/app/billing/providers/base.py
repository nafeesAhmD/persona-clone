from abc import ABC, abstractmethod


class BillingProvider(ABC):
    @abstractmethod
    def create_customer(self, email: str, name: str | None = None) -> dict:
        raise NotImplementedError

    @abstractmethod
    def create_checkout_session(self, customer_id: str, price_id: str, success_url: str, cancel_url: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def cancel_subscription(self, subscription_id: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def retrieve_subscription(self, subscription_id: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def verify_webhook(self, payload: bytes, signature: str | None) -> dict:
        raise NotImplementedError
