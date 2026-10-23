"""Webhook URL safety (SSRF protection).

A webhook URL makes *our server* send requests, so it must never point at our own
network: loopback, private ranges, link-local (cloud metadata at 169.254.169.254),
CGNAT, multicast/reserved space, or internal host names.

Checked twice:
- when a webhook is created or its URL changes (`validate_url`), and
- right before every delivery (`resolve_safe`): the name is resolved again and the
  request is pinned to an address that was checked, so a DNS answer that changes
  after validation ("DNS rebinding") can't redirect it.

Rules:
- https only in production; http is allowed only outside production (and private
  targets are still blocked there).
- no user:password@ in the URL, no other schemes, no fragments.
- IP literals must be canonical (no decimal/octal/hex tricks such as 2130706433,
  0x7f.1 or 0177.0.0.1) and public; IPv4 embedded in IPv6 (mapped, 6to4, NAT64,
  Teredo) is checked as IPv4.
- host names must have a dot and may not be localhost/metadata/internal names.
- every address the name resolves to must be public.
"""

import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit

from app.core.config import get_settings
from app.services.errors import InvalidInputError

MAX_URL_LENGTH = 2000

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata",
    "metadata.google.internal",
    "metadata.goog",
    "metadata.azure.com",
    "instance-data",
    "instance-data.ec2.internal",
    "kubernetes.default",
    "kubernetes.default.svc",
}
_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".intranet",
    ".lan",
    ".home.arpa",
    ".svc",
    ".cluster.local",
)
# Ranges blocked in addition to what Python already treats as non-global.
_EXTRA_BLOCKED = [
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "fec0::/10",
        "ff00::/8",
        "2001:db8::/32",
    )
]
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
# Anything that looks numeric (digits, hex groups, dots) is an IP attempt.
_NUMERIC_HOST = re.compile(r"^(0x[0-9a-f]*|[0-9]+)(\.(0x[0-9a-f]*|[0-9]+))*\.?$", re.IGNORECASE)
_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)


class WebhookUrlError(InvalidInputError):
    """The URL is not allowed as a webhook target (HTTP 400). The message is safe to show."""


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    # IPv4-compatible (deprecated) ::a.b.c.d
    if int(ip) >> 32 == 0:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def is_blocked_ip(value: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything that isn't a plain public unicast address."""
    try:
        ip = ipaddress.ip_address(value) if isinstance(value, str) else value
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.scope_id:
            return True
        embedded = _embedded_v4(ip)
        if embedded is not None and is_blocked_ip(embedded):
            return True
    if any(ip in net for net in _EXTRA_BLOCKED if net.version == ip.version):
        return True
    return (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_host(host: str, port: int) -> list[str]:
    """All addresses for `host` (tests replace this to avoid real DNS)."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def _allowed_schemes() -> set[str]:
    return {"https"} if get_settings().environment == "production" else {"https", "http"}


def _check_host_name(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Return the IP for an IP literal, None for a host name; raise if not allowed."""
    if "%" in host:
        raise WebhookUrlError("Zone ids are not allowed in webhook URLs.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if is_blocked_ip(ip):
            raise WebhookUrlError("Webhook URLs can't point to private, local or reserved addresses.")
        return ip
    if _NUMERIC_HOST.match(host):
        raise WebhookUrlError("Use a normal host name or a standard IP address.")
    name = host.rstrip(".")
    if name in _BLOCKED_HOSTS or name.endswith(_BLOCKED_SUFFIXES):
        raise WebhookUrlError("Webhook URLs can't point to local or internal host names.")
    labels = name.split(".")
    if len(labels) < 2 or not all(_HOST_LABEL.match(label) for label in labels):
        raise WebhookUrlError("Use a public, fully qualified host name (for example hooks.example.com).")
    if labels[-1].isdigit():
        raise WebhookUrlError("Use a normal host name or a standard IP address.")
    return None


def parse(url: str) -> tuple[str, str, int]:
    """Validate the URL's form (no DNS). Returns (normalised url, host, port)."""
    if not isinstance(url, str):
        raise WebhookUrlError("Enter a webhook URL.")
    url = url.strip()
    if not url:
        raise WebhookUrlError("Enter a webhook URL.")
    if len(url) > MAX_URL_LENGTH:
        raise WebhookUrlError(f"Webhook URLs can be at most {MAX_URL_LENGTH} characters.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch == "\\" for ch in url):
        raise WebhookUrlError("The webhook URL contains characters that aren't allowed.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise WebhookUrlError("That doesn't look like a valid URL.") from None
    scheme = parts.scheme.lower()
    if scheme not in _allowed_schemes():
        if scheme == "http":
            raise WebhookUrlError("Webhook URLs must use https.")
        raise WebhookUrlError("Webhook URLs must start with https://.")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise WebhookUrlError("Webhook URLs can't contain a user name or password.")
    if parts.fragment:
        raise WebhookUrlError("Webhook URLs can't contain a #fragment.")
    host = (parts.hostname or "").lower()
    if not host:
        raise WebhookUrlError("The webhook URL needs a host name.")
    try:
        host.encode("ascii")
    except UnicodeEncodeError:
        raise WebhookUrlError("Use the punycode (xn--) form for international host names.") from None
    if port == 0:
        raise WebhookUrlError("That port isn't allowed.")
    _check_host_name(host)
    port = port or (443 if scheme == "https" else 80)
    netloc = parts.netloc.lower()
    normalised = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
    return normalised, host, port


def resolve_safe(host: str, port: int) -> list[str]:
    """Resolve `host` and return its addresses, refusing if any of them is private."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if is_blocked_ip(literal):
            raise WebhookUrlError("Webhook URLs can't point to private, local or reserved addresses.")
        return [str(literal)]
    try:
        addresses = resolve_host(host.rstrip("."), port)
    except (OSError, UnicodeError):
        raise WebhookUrlError("We couldn't find that host. Check the URL.") from None
    if not addresses:
        raise WebhookUrlError("We couldn't find that host. Check the URL.")
    if any(is_blocked_ip(address) for address in addresses):
        raise WebhookUrlError("Webhook URLs can't point to private, local or reserved addresses.")
    return addresses


def validate_url(url: str, *, resolve: bool = True) -> str:
    """Full check used at create/update: form, then DNS. Returns the normalised URL."""
    normalised, host, port = parse(url)
    if resolve:
        resolve_safe(host, port)
    return normalised
