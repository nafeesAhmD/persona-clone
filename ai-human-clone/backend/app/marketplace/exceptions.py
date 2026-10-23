"""Marketplace errors: a stable `code`, an HTTP status and a safe message
(docs/phase18/contract.md). Rendered as {"detail": message, "code": code, ...extra}."""

ERRORS: dict[str, tuple[int, str]] = {
    "discovery_off": (403, "Clone discovery is turned off on this platform."),
    "not_found": (404, "AI Clone not found."),
    "confirmation_required": (409, "Confirm that this AI Clone may be listed publicly in the marketplace."),
    "not_eligible": (409, "This AI Clone can't be listed yet: see the requirements."),
    "report_not_found": (404, "Report not found."),
}


class MarketplaceError(Exception):
    def __init__(self, code: str, message: str | None = None, *, extra: dict | None = None) -> None:
        self.status_code, default_message = ERRORS.get(code, (400, "The request couldn't be completed."))
        self.code = code
        self.message = message or default_message
        self.extra = extra or {}
        super().__init__(self.message)
