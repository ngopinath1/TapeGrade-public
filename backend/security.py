"""Keep the single-user API and its media on the local machine."""

from ipaddress import ip_address
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
LOCAL_ORIGINS = {
    f"http://{host}:{port}" for host in ("localhost", "127.0.0.1", "[::1]") for port in (5173, 8000)
}


def local_host(authority: str) -> bool:
    try:
        value = urlsplit("//" + authority)
        return (
            value.hostname in LOCAL_HOSTS
            and value.username is None
            and value.password is None
            and not value.path
            and not value.query
            and not value.fragment
            and (value.port is None or 1 <= value.port <= 65535)
        )
    except ValueError:
        return False


class LocalOnlyMiddleware:
    """Reject remote clients, DNS rebinding, and cross-site browser requests.

    This is a local-use boundary, not a login system. A local reverse proxy or
    tunnel must never be used to expose this shared workspace to the internet.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        client = scope.get("client")
        try:
            loopback = bool(client and ip_address(client[0]).is_loopback)
        except ValueError:
            loopback = False
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        allowed = (
            loopback
            and local_host(headers.get("host", ""))
            and (origin is None or origin in LOCAL_ORIGINS)
            and headers.get("sec-fetch-site") != "cross-site"
        )
        if allowed:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        response = JSONResponse(
            {"detail": "TapeGrade accepts local requests only."}, status_code=403
        )
        await response(scope, receive, send)
