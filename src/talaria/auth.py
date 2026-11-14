"""Single-owner authentication and browser request protection."""

import hashlib
import hmac
import secrets
import time
from collections import OrderedDict
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

from starlette.requests import Request

COOKIE = "talaria_session"
TTL = 60 * 60 * 24 * 14


def cookie_name(base_path: str, *, development: bool = False) -> str:
    name = "talaria_dev_session" if development else COOKIE
    if base_path:
        name += "_" + hashlib.sha256(base_path.encode()).hexdigest()[:10]
    return name


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1)
    return f"{salt}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not isinstance(password, str) or len(password) > 1024 or not isinstance(stored, str):
        return False
    salt, separator, expected = stored.partition(":")
    if not separator or len(salt) != 32 or len(expected) != 128 or not expected.isascii():
        return False
    try:
        digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1)
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(digest.hex(), expected)


def signature(settings, message: str) -> str:
    return hmac.new(settings.signing_key.encode(), message.encode(), "sha256").hexdigest()


def issue_cookie(settings, user_id="1") -> str:
    payload = f"{int(time.time())}.{user_id}.{secrets.token_hex(16)}"
    return f"{payload}.{signature(settings, payload)}"


def cookie_user_id(request):
    value = request.cookies.get(request.app.state.cookie_name, "")
    try:
        timestamp, user_id, nonce, sig = value.split(".")
        if not user_id.isdigit():
            return None
        age = time.time() - int(timestamp)
        if not 0 <= age < TTL:
            return None
        payload = f"{timestamp}.{user_id}.{nonce}"
        if not hmac.compare_digest(signature(request.app.state.settings, payload), sig):
            return None
        if request.app.state.revocations.contains(value):
            return None
        user_id = int(user_id)
        user = request.app.state.users.get(user_id)
        return user_id if user and user["enabled"] else None
    except (ValueError, TypeError):
        return None


def authenticated(request: Request) -> bool:
    return cookie_user_id(request) is not None


def csrf_token(request: Request) -> str:
    return signature(
        request.app.state.settings,
        "csrf:" + request.cookies.get(request.app.state.cookie_name, ""),
    )


def browser_request_valid(request: Request, *, login: bool = False) -> bool:
    base = urlsplit(str(request.base_url))
    expected = request.app.state.settings.public_origin or f"{base.scheme}://{base.netloc}"
    origin = request.headers.get("origin")
    if origin and origin != expected:
        return False
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    if request.headers.get("x-talaria-request") != "1":
        return False
    supplied = request.headers.get("x-csrf-token", "")
    return login or (supplied.isascii() and hmac.compare_digest(supplied, csrf_token(request)))


class LoginLimiter:
    def __init__(self, trusted_proxies=()):
        self.trusted_proxies = tuple(ip_network(value) for value in trusted_proxies)
        self.failures: OrderedDict[str, list[float]] = OrderedDict()

    def address(self, request: Request) -> str:
        peer = request.client.host if request.client else "local"
        forwarded = request.headers.get("x-forwarded-for", "")
        if not self.trusted_proxies or len(forwarded) > 2048:
            return peer
        try:
            address = ip_address(peer)
            for hop in reversed(forwarded.split(",")):
                if not any(address in network for network in self.trusted_proxies):
                    break
                address = ip_address(hop.strip())
            return str(address)
        except ValueError:
            return peer

    def allow(self, address: str) -> bool:
        now = time.monotonic()
        times = [t for t in self.failures.pop(address, []) if now - t < 3600]
        self.failures[address] = times
        while len(self.failures) > 1024:
            self.failures.popitem(last=False)
        if len(times) >= 30:
            return False
        times.append(now)
        return True

    def success(self, address: str) -> None:
        self.failures.pop(address, None)
