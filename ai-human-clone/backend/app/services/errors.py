class NotFoundError(Exception):
    """A requested resource doesn't exist (mapped to HTTP 404)."""


class InvalidInputError(ValueError):
    """The client sent something we can't process (mapped to HTTP 400)."""


class AuthenticationError(Exception):
    """Missing/invalid credentials or session (mapped to HTTP 401)."""


class ForbiddenError(Exception):
    """Authenticated, but not allowed: inactive account or someone else's resource (HTTP 403)."""


MAINTENANCE = "System is temporarily under maintenance."


class MaintenanceError(Exception):
    """Maintenance mode is on (HTTP 503)."""


class ConflictError(Exception):
    """A unique value such as email or username is already taken (mapped to HTTP 409)."""
