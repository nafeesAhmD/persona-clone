class BillingError(Exception):
    status_code = 400
    user_message = "Billing error occurred."


class UsageLimitError(BillingError):
    status_code = 429
    user_message = "Usage limit reached."


class BillingDisabledError(BillingError):
    status_code = 403
    user_message = "Billing is disabled."
