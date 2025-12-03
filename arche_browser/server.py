"""
MCP Server for browser automation.

Exposes all browser functionality as MCP tools.
"""

import sys
import base64
import atexit
import socket
import threading
import ipaddress
from pathlib import Path
from typing import Any, Dict, List, Optional

from .chrome import Chrome
from .browser import Browser
from .auth import TokenAuth, create_auth_middleware


# Global state with thread safety
_lock = threading.Lock()
_chrome: Optional[Chrome] = None
_browser: Optional[Browser] = None
_auth: Optional[TokenAuth] = None


def get_browser() -> Browser:
    """Get or create browser instance (thread-safe)."""
    global _chrome, _browser

    with _lock:
        if _browser is None or _browser.cdp._ws is None:
            if _chrome is None:
                _chrome = Chrome()
                _chrome.start()
            _browser = Browser(f"localhost:{_chrome.port}")

    return _browser


def cleanup():
    """Cleanup on exit."""
    global _chrome, _browser
    try:
        if _browser:
            _browser.close()
    except Exception:
        pass
    finally:
        _browser = None

    try:
        if _chrome:
            _chrome.stop()
    except Exception:
        pass
    finally:
        _chrome = None


atexit.register(cleanup)


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

    # Generate self-signed certificate
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        # Generate key
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        # Generate certificate
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

        # Write files
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
        # Fallback: use openssl command
        import subprocess
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key_file), "-out", str(cert_file),
            "-days", "365", "-nodes",
            "-subj", "/CN=arche-browser"
        ], check=True, capture_output=True)
        return str(cert_file), str(key_file)


def create_server(headless: bool = False, local_control: bool = False, browser_tools: bool = True):
    """Create MCP server with all browser tools.

    Args:
        headless: Run Chrome in headless mode
        local_control: Enable full local PC control (shell, python, files, etc.)
        browser_tools: Enable browser automation tools (default: True)
    """
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    # Configure Chrome
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

    # Disable DNS rebinding protection to allow remote access
    # Token authentication provides security for remote access
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    mcp = FastMCP(
        name=name,
        instructions=". ".join(instructions),
        transport_security=security_settings
    )

    # Register local control tools if enabled
    if local_control:
        from .local import LocalControl, register_local_tools
        local = LocalControl()
        register_local_tools(mcp, local)

    # Skip browser tools if disabled
    if not browser_tools:
        return mcp

    # ═══════════════════════════════════════════════════════════════
    # Navigation
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def goto(url: str) -> str:
        """Navigate to URL. Returns final URL."""
        b = get_browser()
        b.goto(url)
        return b.url

    @mcp.tool()
    def get_url() -> str:
        """Get current page URL."""
        return get_browser().url

    @mcp.tool()
    def get_title() -> str:
        """Get current page title."""
        return get_browser().title

    @mcp.tool()
    def reload(ignore_cache: bool = False) -> str:
        """Reload page. Returns URL."""
        b = get_browser()
        b.reload(ignore_cache)
        return b.url

    @mcp.tool()
    def go_back() -> str:
        """Go back in history. Returns URL."""
        b = get_browser()
        b.back()
        return b.url

    @mcp.tool()
    def go_forward() -> str:
        """Go forward in history. Returns URL."""
        b = get_browser()
        b.forward()
        return b.url

    # ═══════════════════════════════════════════════════════════════
    # DOM
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def get_text(selector: str = "body") -> str:
        """Get text content of element."""
        return get_browser().text(selector)

    @mcp.tool()
    def get_html(selector: str = "body") -> str:
        """Get inner HTML of element."""
        return get_browser().html(selector)

    @mcp.tool()
    def get_outer_html(selector: str = "body") -> str:
        """Get outer HTML of element."""
        return get_browser().outer_html(selector)

    @mcp.tool()
    def get_attr(selector: str, name: str) -> Optional[str]:
        """Get element attribute value."""
        return get_browser().attr(selector, name)

    @mcp.tool()
    def set_attr(selector: str, name: str, value: str) -> bool:
        """Set element attribute."""
        return get_browser().set_attr(selector, name, value)

    @mcp.tool()
    def get_value(selector: str) -> Optional[str]:
        """Get input element value."""
        return get_browser().value(selector)

    @mcp.tool()
    def query(selector: str) -> bool:
        """Check if element exists."""
        return get_browser().query(selector)

    @mcp.tool()
    def query_count(selector: str) -> int:
        """Count matching elements."""
        return get_browser().query_all(selector)

    # ═══════════════════════════════════════════════════════════════
    # Input
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def click(selector: str) -> bool:
        """Click element."""
        return get_browser().click(selector)

    @mcp.tool()
    def type_text(selector: str, text: str, clear: bool = True) -> bool:
        """Type text into input element."""
        return get_browser().type(selector, text, clear)

    @mcp.tool()
    def focus(selector: str) -> bool:
        """Focus element."""
        return get_browser().focus(selector)

    @mcp.tool()
    def select_option(selector: str, value: str) -> bool:
        """Select dropdown option by value."""
        return get_browser().select(selector, value)

    @mcp.tool()
    def check_box(selector: str, checked: bool = True) -> bool:
        """Check or uncheck checkbox."""
        return get_browser().check(selector, checked)

    @mcp.tool()
    def scroll_to(x: int = 0, y: int = 0, selector: Optional[str] = None) -> bool:
        """Scroll page or element."""
        get_browser().scroll(x, y, selector)
        return True

    @mcp.tool()
    def scroll_into_view(selector: str) -> bool:
        """Scroll element into view."""
        return get_browser().scroll_into_view(selector)

    # ═══════════════════════════════════════════════════════════════
    # Waiting
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def wait_for(selector: str, timeout: int = 30) -> bool:
        """Wait for element to appear."""
        return get_browser().wait(selector, timeout)

    @mcp.tool()
    def wait_gone(selector: str, timeout: int = 30) -> bool:
        """Wait for element to disappear."""
        return get_browser().wait_gone(selector, timeout)

    @mcp.tool()
    def wait_for_text(text: str, timeout: int = 30) -> bool:
        """Wait for text to appear on page."""
        return get_browser().wait_text(text, timeout)

    # ═══════════════════════════════════════════════════════════════
    # JavaScript
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def evaluate(script: str, timeout: int = 30) -> Any:
        """Execute JavaScript and return result."""
        return get_browser().eval(script, timeout)

    # ═══════════════════════════════════════════════════════════════
    # HTTP via Browser
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def fetch(path: str, method: str = "GET", body: Optional[Dict] = None,
              headers: Optional[Dict] = None) -> Any:
        """Make HTTP request through browser (uses cookies, bypasses CORS)."""
        return get_browser().fetch(path, method, body, headers)

    # ═══════════════════════════════════════════════════════════════
    # Screenshots & PDF
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def screenshot(path: Optional[str] = None, full_page: bool = False,
                   selector: Optional[str] = None) -> str:
        """Take screenshot. Returns base64 or saves to path."""
        data = get_browser().screenshot(path, full_page, selector)
        if path:
            return f"Saved to {path}"
        return base64.b64encode(data).decode()

    @mcp.tool()
    def pdf(path: Optional[str] = None) -> str:
        """Generate PDF (headless only). Returns base64 or saves to path."""
        data = get_browser().pdf(path)
        if path:
            return f"Saved to {path}"
        return base64.b64encode(data).decode()

    # ═══════════════════════════════════════════════════════════════
    # Cookies
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def get_cookies(urls: Optional[List[str]] = None) -> List[Dict]:
        """Get cookies."""
        return get_browser().cookies(urls)

    @mcp.tool()
    def set_cookie(name: str, value: str, domain: Optional[str] = None) -> bool:
        """Set cookie."""
        return get_browser().set_cookie(name, value, domain)

    @mcp.tool()
    def delete_cookies(name: str, domain: Optional[str] = None) -> bool:
        """Delete cookies by name."""
        get_browser().delete_cookies(name, domain)
        return True

    @mcp.tool()
    def clear_all_cookies() -> bool:
        """Clear all cookies."""
        get_browser().clear_cookies()
        return True

    # ═══════════════════════════════════════════════════════════════
    # Storage
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def storage_get(key: str, local: bool = True) -> Optional[str]:
        """Get localStorage or sessionStorage item."""
        return get_browser().storage_get(key, local)

    @mcp.tool()
    def storage_set(key: str, value: str, local: bool = True) -> bool:
        """Set localStorage or sessionStorage item."""
        get_browser().storage_set(key, value, local)
        return True

    @mcp.tool()
    def storage_remove(key: str, local: bool = True) -> bool:
        """Remove storage item."""
        get_browser().storage_remove(key, local)
        return True

    @mcp.tool()
    def storage_clear(local: bool = True) -> bool:
        """Clear storage."""
        get_browser().storage_clear(local)
        return True

    # ═══════════════════════════════════════════════════════════════
    # Console
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def console_messages(timeout: float = 1.0) -> List[Dict]:
        """Get console messages."""
        b = get_browser()
        b.console_enable()
        return b.console_messages(timeout)

    # ═══════════════════════════════════════════════════════════════
    # Network
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def network_enable() -> bool:
        """Enable network monitoring."""
        get_browser().network_enable()
        return True

    @mcp.tool()
    def network_requests(timeout: float = 1.0) -> List[Dict]:
        """Get recent network requests."""
        return get_browser().network_requests(timeout)

    # ═══════════════════════════════════════════════════════════════
    # Emulation
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def set_viewport(width: int, height: int, scale: float = 1.0, mobile: bool = False) -> bool:
        """Set viewport size."""
        get_browser().viewport(width, height, scale, mobile)
        return True

    @mcp.tool()
    def set_user_agent(ua: str) -> bool:
        """Set user agent string."""
        get_browser().user_agent(ua)
        return True

    @mcp.tool()
    def set_geolocation(lat: float, lon: float, accuracy: float = 100) -> bool:
        """Set geolocation."""
        get_browser().geolocation(lat, lon, accuracy)
        return True

    @mcp.tool()
    def set_timezone(tz: str) -> bool:
        """Set timezone (e.g., 'Asia/Seoul')."""
        get_browser().timezone(tz)
        return True

    @mcp.tool()
    def set_offline(offline: bool = True) -> bool:
        """Enable/disable offline mode."""
        get_browser().offline(offline)
        return True

    @mcp.tool()
    def throttle_network(download: int = -1, upload: int = -1, latency: int = 0) -> bool:
        """Throttle network speed (bytes/sec, -1 for unlimited)."""
        get_browser().throttle(download, upload, latency)
        return True

    # ═══════════════════════════════════════════════════════════════
    # Input Events
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def mouse_move(x: int, y: int) -> bool:
        """Move mouse to coordinates."""
        get_browser().mouse_move(x, y)
        return True

    @mcp.tool()
    def mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
        """Click at coordinates."""
        get_browser().mouse_click(x, y, button, clicks)
        return True

    @mcp.tool()
    def mouse_wheel(x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> bool:
        """Scroll with mouse wheel."""
        get_browser().mouse_wheel(x, y, delta_x, delta_y)
        return True

    @mcp.tool()
    def key_press(key: str) -> bool:
        """Press a key."""
        get_browser().key_press(key)
        return True

    @mcp.tool()
    def key_type(text: str) -> bool:
        """Type text character by character."""
        get_browser().key_type(text)
        return True

    # ═══════════════════════════════════════════════════════════════
    # Dialogs
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def handle_dialog(accept: bool = True, text: Optional[str] = None) -> bool:
        """Handle JavaScript alert/confirm/prompt dialog."""
        get_browser().dialog_handle(accept, text)
        return True

    # ═══════════════════════════════════════════════════════════════
    # Frames
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def get_frames() -> List[Dict]:
        """Get all frames in page."""
        return get_browser().frames()

    # ═══════════════════════════════════════════════════════════════
    # Performance
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def get_performance_metrics() -> Dict[str, float]:
        """Get performance metrics."""
        return get_browser().performance_metrics()

    # ═══════════════════════════════════════════════════════════════
    # Pages/Tabs
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def get_pages() -> List[Dict]:
        """List all browser pages/tabs."""
        return get_browser().pages()

    @mcp.tool()
    def new_page(url: str = "about:blank") -> Dict:
        """Open new page/tab."""
        return get_browser().new_page(url)

    @mcp.tool()
    def close_page(page_id: str) -> bool:
        """Close page/tab by ID."""
        return get_browser().close_page(page_id)

    # ═══════════════════════════════════════════════════════════════
    # Debugging
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def highlight_element(selector: str) -> bool:
        """Highlight element on page."""
        get_browser().highlight(selector)
        return True

    @mcp.tool()
    def hide_highlight() -> bool:
        """Hide element highlight."""
        get_browser().hide_highlight()
        return True

    @mcp.tool()
    def get_accessibility_tree() -> Dict:
        """Get accessibility tree."""
        return get_browser().accessibility_tree()

    return mcp


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
    """Run MCP server.

    Args:
        transport: 'stdio' or 'sse'
        port: Port for SSE server
        headless: Run Chrome in headless mode
        auth: Enable token authentication for SSE
        token: Custom auth token
        local_control: Enable full local PC control
        browser_tools: Enable browser automation tools
        no_launch: Don't launch Chrome (connect to existing)
        chrome_port: Chrome debugging port
    """
    global _auth, _chrome

    # Set Chrome port
    Chrome.DEFAULT_PORT = chrome_port

    mcp = create_server(headless, local_control, browser_tools)

    # Start browser immediately if browser tools are enabled
    if browser_tools:
        if no_launch:
            # Manual mode - print instructions
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
        # Get IP addresses
        local_ip = get_local_ip()
        public_ip = get_public_ip()

        # Generate SSL certificates
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

            # Run with auth middleware
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
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.types import ASGIApp, Receive, Scope, Send

    import re
    # UUID pattern for session validation
    SESSION_ID_PATTERN = re.compile(r'^[a-f0-9]{32}$')

    class AuthMiddleware:
        """Pure ASGI middleware for token authentication (SSE compatible)."""

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

            # Allow /messages with valid session_id format
            # Session IDs are cryptographically random UUIDs from FastMCP
            # Only clients who connected to authenticated /sse can get session IDs
            if path.startswith("/messages"):
                session_id = query_params.get("session_id", [""])[0]
                if session_id and SESSION_ID_PATTERN.match(session_id):
                    await self.app(scope, receive, send)
                    return

            # For other endpoints (like /sse), require token auth
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

    # Get the SSE app from FastMCP and add middleware
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    app = mcp.sse_app()

    # Wrap with auth middleware (pure ASGI, SSE compatible)
    app = AuthMiddleware(app)

    # Configure uvicorn with optional SSL
    config = {
        "host": "0.0.0.0",
        "port": port,
        "log_level": "warning"
    }
    if ssl_certfile and ssl_keyfile:
        config["ssl_certfile"] = ssl_certfile
        config["ssl_keyfile"] = ssl_keyfile

    uvicorn.run(app, **config)
