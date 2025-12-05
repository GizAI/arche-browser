"""
MCP Server for browser automation.

Exposes all browser functionality as MCP tools.
"""

import sys
import atexit
import socket
import threading
import ipaddress
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID

from .chrome import Chrome
from .browser import Browser
from .context import BrowserContext
from .auth import TokenAuth


# ══════════════════════════════════════════════════════════════════════════════
# Monkey-patch MCP session to auto-initialize on any request
# ══════════════════════════════════════════════════════════════════════════════
def _patch_mcp_session():
    """Patch MCP ServerSession to auto-initialize on first request."""
    try:
        from mcp.server import session as mcp_session
        import mcp.types as types

        _original_received_request = mcp_session.ServerSession._received_request

        async def _patched_received_request(self, responder):
            if self._initialization_state != mcp_session.InitializationState.Initialized:
                match responder.request.root:
                    case types.InitializeRequest():
                        pass
                    case types.PingRequest():
                        pass
                    case _:
                        print("[*] Auto-initializing session (client skipped handshake)", file=sys.stderr)
                        self._initialization_state = mcp_session.InitializationState.Initialized

            return await _original_received_request(self, responder)

        mcp_session.ServerSession._received_request = _patched_received_request
        print("[*] MCP session patched for auto-initialization", file=sys.stderr)
    except Exception as e:
        print(f"[!] Failed to patch MCP session: {e}", file=sys.stderr)


_patch_mcp_session()


# ══════════════════════════════════════════════════════════════════════════════
# Global state with thread safety
# ══════════════════════════════════════════════════════════════════════════════
_lock = threading.Lock()
_chrome: Optional[Chrome] = None
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_auth: Optional[TokenAuth] = None


def get_browser() -> Browser:
    """Get or create browser instance (thread-safe)."""
    global _chrome, _browser, _context

    with _lock:
        if _chrome is not None and not _chrome.running:
            print("[*] Chrome process died, restarting...", file=sys.stderr)
            _browser = None
            _chrome = None
            _context = None

        if _browser is not None and _browser.cdp._ws is None:
            print("[*] Browser connection lost, reconnecting...", file=sys.stderr)
            _browser = None
            _context = None

        if _browser is None:
            if _chrome is None:
                _chrome = Chrome()
                _chrome.start()
                print(f"[*] Chrome started on port {_chrome.port}", file=sys.stderr)
            _browser = Browser(f"localhost:{_chrome.port}")
            _context = BrowserContext(browser=_browser)
            print("[*] Browser connected", file=sys.stderr)

    return _browser


def get_context() -> BrowserContext:
    """Get browser context (ensures browser is connected)."""
    global _context
    get_browser()  # Ensure browser is connected
    return _context


def cleanup():
    """Cleanup on exit."""
    global _chrome, _browser, _context
    try:
        if _browser:
            _browser.close()
    except Exception:
        pass
    finally:
        _browser = None
        _context = None

    try:
        if _chrome:
            _chrome.stop()
    except Exception:
        pass
    finally:
        _chrome = None


atexit.register(cleanup)


# ══════════════════════════════════════════════════════════════════════════════
# Network utilities
# ══════════════════════════════════════════════════════════════════════════════
def get_local_ip() -> str:
    """Get local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_public_ip() -> Optional[str]:
    """Get public IP address."""
    import requests
    try:
        resp = requests.get("https://api.ipify.org", timeout=3)
        return resp.text.strip()
    except Exception:
        try:
            resp = requests.get("https://ifconfig.me/ip", timeout=3)
            return resp.text.strip()
        except Exception:
            return None


def ensure_ssl_certs() -> tuple:
    """Ensure SSL certificates exist, generate if needed."""
    cert_dir = Path.home() / ".arche-browser" / "ssl"
    cert_dir.mkdir(parents=True, exist_ok=True)

    cert_file = cert_dir / "cert.pem"
    key_file = cert_dir / "key.pem"

    if cert_file.exists() and key_file.exists():
        return str(cert_file), str(key_file)

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "arche-browser"),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.DNSName("*"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        with open(key_file, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        return str(cert_file), str(key_file)

    except ImportError:
        import subprocess
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key_file), "-out", str(cert_file),
            "-days", "365", "-nodes",
            "-subj", "/CN=arche-browser"
        ], check=True, capture_output=True)
        return str(cert_file), str(key_file)


# ══════════════════════════════════════════════════════════════════════════════
# Server creation
# ══════════════════════════════════════════════════════════════════════════════
def create_server(headless: bool = False, local_control: bool = False, browser_tools: bool = True):
    """Create MCP server with all browser tools."""
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    Chrome.DEFAULT_HEADLESS = headless

    name = "arche-browser"
    if local_control and not browser_tools:
        name = "arche-local"
    elif local_control:
        name = "arche-full"

    instructions = []
    if browser_tools:
        instructions.append("Browser automation via Chrome DevTools Protocol")
    if local_control:
        instructions.append("Full local PC control: shell commands, Python execution, file system, clipboard, processes")

    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    mcp = FastMCP(
        name=name,
        instructions=". ".join(instructions),
        transport_security=security_settings
    )

    if local_control:
        from .local import LocalControl, register_local_tools
        local = LocalControl()
        register_local_tools(mcp, local)

    if not browser_tools:
        return mcp

    # Register all browser tools
    from .tools import register_browser_tools
    register_browser_tools(mcp, get_browser, get_context)

    return mcp


# ══════════════════════════════════════════════════════════════════════════════
# Server run
# ══════════════════════════════════════════════════════════════════════════════
def run(
    transport: str = "stdio",
    port: int = 8080,
    headless: bool = False,
    auth: bool = True,
    token: Optional[str] = None,
    local_control: bool = False,
    browser_tools: bool = True,
    no_launch: bool = False,
    chrome_port: int = 9222
):
    """Run MCP server."""
    global _auth

    Chrome.DEFAULT_PORT = chrome_port
    mcp = create_server(headless, local_control, browser_tools)

    if browser_tools:
        if no_launch:
            print(f"[*] Manual browser mode - Chrome will NOT be launched automatically", file=sys.stderr)
            print(f"[*] Start Chrome manually with remote debugging:", file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"    Windows:", file=sys.stderr)
            print(f'    chrome.exe --remote-debugging-port={chrome_port} --remote-allow-origins=*', file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"    Mac:", file=sys.stderr)
            print(f'    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port={chrome_port} --remote-allow-origins=*', file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"    Linux:", file=sys.stderr)
            print(f'    google-chrome --remote-debugging-port={chrome_port} --remote-allow-origins=*', file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"[*] Waiting for Chrome on port {chrome_port}...", file=sys.stderr)
        else:
            print(f"[*] Starting Chrome {'(headless)' if headless else '(visible)'}...", file=sys.stderr)
            try:
                browser = get_browser()
                print(f"[*] Chrome ready at localhost:{browser.cdp.address.split(':')[1]}", file=sys.stderr)
            except Exception as e:
                print(f"[!] Chrome failed to start: {e}", file=sys.stderr)
                print(f"[!] Browser tools will not be available", file=sys.stderr)

    if transport == "sse":
        local_ip = get_local_ip()
        public_ip = get_public_ip()

        try:
            cert_file, key_file = ensure_ssl_certs()
            use_ssl = True
            protocol = "https"
        except Exception as e:
            print(f"[!] SSL certificate generation failed: {e}", file=sys.stderr)
            print(f"[!] Falling back to HTTP (not secure for remote access)", file=sys.stderr)
            cert_file, key_file = None, None
            use_ssl = False
            protocol = "http"

        if auth:
            _auth = TokenAuth(token)
            auth_token = _auth.token

            print(f"", file=sys.stderr)
            print(f"[*] Arche Browser MCP Server (SSE)", file=sys.stderr)
            print(f"[*] Port: {port}", file=sys.stderr)
            print(f"[*] Protocol: {protocol.upper()}", file=sys.stderr)
            print(f"[*] Auth: ENABLED", file=sys.stderr)
            print(f"[*] Token: {auth_token}", file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"[*] Network:", file=sys.stderr)
            print(f"    Local:  {local_ip}", file=sys.stderr)
            if public_ip:
                print(f"    Public: {public_ip}", file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"[*] Connect URLs:", file=sys.stderr)
            print(f"    {protocol}://localhost:{port}/sse?token={auth_token}", file=sys.stderr)
            print(f"    {protocol}://{local_ip}:{port}/sse?token={auth_token}", file=sys.stderr)
            if public_ip:
                print(f"    {protocol}://{public_ip}:{port}/sse?token={auth_token}", file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"[*] Claude Code MCP config:", file=sys.stderr)
            print(f'    {{"url": "{protocol}://{local_ip}:{port}/sse?token={auth_token}"}}', file=sys.stderr)
            if use_ssl:
                print(f"", file=sys.stderr)
                print(f"[*] SSL Certificate: {cert_file}", file=sys.stderr)

            run_sse_with_auth(mcp, port, _auth, cert_file, key_file)
        else:
            print(f"", file=sys.stderr)
            print(f"[*] Arche Browser MCP Server (SSE)", file=sys.stderr)
            print(f"[*] Port: {port}", file=sys.stderr)
            print(f"[*] Protocol: {protocol.upper()}", file=sys.stderr)
            print(f"[*] Auth: DISABLED (not recommended)", file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"[*] Network:", file=sys.stderr)
            print(f"    Local:  {local_ip}", file=sys.stderr)
            if public_ip:
                print(f"    Public: {public_ip}", file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"[*] URL: {protocol}://localhost:{port}/sse", file=sys.stderr)
            mcp.settings.port = port
            mcp.run(transport="sse")
    else:
        print("[*] Arche Browser MCP Server (stdio)", file=sys.stderr)
        mcp.run()


def run_sse_with_auth(mcp, port: int, auth: TokenAuth,
                      ssl_certfile: Optional[str] = None,
                      ssl_keyfile: Optional[str] = None):
    """Run SSE server with authentication middleware and optional SSL."""
    import re
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse, Response
    from starlette.requests import Request
    from starlette.types import ASGIApp, Receive, Scope, Send
    from mcp.server.sse import SseServerTransport
    from mcp.server.transport_security import TransportSecuritySettings

    SESSION_ID_PATTERN = re.compile(r'^[a-f0-9]{32}$')
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    sse_transport = SseServerTransport("/messages/", security_settings=security_settings)

    async def handle_sse(request: Request):
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            read_stream, write_stream = streams
            await mcp._mcp_server.run(
                read_stream,
                write_stream,
                mcp._mcp_server.create_initialization_options()
            )
        return Response()

    async def handle_messages(request: Request):
        session_id = request.query_params.get("session_id", "")
        try:
            session_uuid = UUID(hex=session_id)
            if session_uuid not in sse_transport._read_stream_writers:
                return Response(
                    content='{"jsonrpc":"2.0","error":{"code":-32000,"message":"Session expired. Please reconnect SSE."},"id":null}',
                    status_code=410,
                    media_type="application/json"
                )
        except (ValueError, AttributeError):
            pass

        return await sse_transport.handle_post_message(
            request.scope, request.receive, request._send
        )

    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Route("/messages/", endpoint=handle_messages, methods=["POST"]),
    ]

    async def lifespan(app):
        print("[*] SSE server starting...", file=sys.stderr)
        yield
        print("[*] SSE server shutting down...", file=sys.stderr)

    starlette_app = Starlette(routes=routes, lifespan=lifespan)

    class AuthMiddleware:
        def __init__(self, app: ASGIApp):
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            path = scope.get("path", "")
            from urllib.parse import parse_qs
            query_string = scope.get("query_string", b"").decode()
            query_params = parse_qs(query_string)

            if path.startswith("/messages"):
                session_id = query_params.get("session_id", [""])[0]
                if session_id and SESSION_ID_PATTERN.match(session_id):
                    await self.app(scope, receive, send)
                    return

            token = query_params.get("token", [""])[0]

            if not token:
                headers = dict(scope.get("headers", []))
                auth_header = headers.get(b"authorization", b"").decode()
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]

            if not auth.verify(token):
                response = JSONResponse(
                    {"error": "Unauthorized - Invalid or missing token"},
                    status_code=401
                )
                await response(scope, receive, send)
                return

            await self.app(scope, receive, send)

    app = AuthMiddleware(starlette_app)

    config = {
        "host": "0.0.0.0",
        "port": port,
        "log_level": "warning"
    }
    if ssl_certfile and ssl_keyfile:
        config["ssl_certfile"] = ssl_certfile
        config["ssl_keyfile"] = ssl_keyfile

    uvicorn.run(app, **config)
