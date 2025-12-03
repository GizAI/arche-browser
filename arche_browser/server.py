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
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from .chrome import Chrome
from .browser import Browser
from .auth import TokenAuth, create_auth_middleware


# ══════════════════════════════════════════════════════════════════════════════
# Monkey-patch MCP session to auto-initialize on any request
# This allows clients to call tools without explicit initialize handshake
# ══════════════════════════════════════════════════════════════════════════════
def _patch_mcp_session():
    """Patch MCP ServerSession to auto-initialize on first request."""
    try:
        from mcp.server import session as mcp_session
        import mcp.types as types

        _original_received_request = mcp_session.ServerSession._received_request

        async def _patched_received_request(self, responder):
            """Auto-initialize if not initialized and request is not initialize."""
            # Auto-initialize on first non-initialize request
            if self._initialization_state != mcp_session.InitializationState.Initialized:
                match responder.request.root:
                    case types.InitializeRequest():
                        pass  # Let original handle it
                    case types.PingRequest():
                        pass  # Always allowed
                    case _:
                        # Auto-initialize with default params
                        print("[*] Auto-initializing session (client skipped handshake)", file=sys.stderr)
                        self._initialization_state = mcp_session.InitializationState.Initialized

            return await _original_received_request(self, responder)

        mcp_session.ServerSession._received_request = _patched_received_request
        print("[*] MCP session patched for auto-initialization", file=sys.stderr)
    except Exception as e:
        print(f"[!] Failed to patch MCP session: {e}", file=sys.stderr)


# Apply patch on module load
_patch_mcp_session()


# Global state with thread safety
_lock = threading.Lock()
_chrome: Optional[Chrome] = None
_browser: Optional[Browser] = None
_auth: Optional[TokenAuth] = None

# Session persistence: map old session IDs to new ones
_session_redirects: Dict[str, str] = {}
_active_sessions: Dict[str, Any] = {}


def get_browser() -> Browser:
    """Get or create browser instance (thread-safe).

    Automatically restarts Chrome if it was closed.
    """
    global _chrome, _browser

    with _lock:
        # Check if Chrome process died
        if _chrome is not None and not _chrome.running:
            print("[*] Chrome process died, restarting...", file=sys.stderr)
            _browser = None
            _chrome = None

        # Check if WebSocket connection is dead
        if _browser is not None and _browser.cdp._ws is None:
            print("[*] Browser connection lost, reconnecting...", file=sys.stderr)
            _browser = None

        # Start Chrome and connect browser
        if _browser is None:
            if _chrome is None:
                _chrome = Chrome()
                _chrome.start()
                print(f"[*] Chrome started on port {_chrome.port}", file=sys.stderr)
            _browser = Browser(f"localhost:{_chrome.port}")
            print("[*] Browser connected", file=sys.stderr)

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
    # CONSOLIDATED TOOLS (Token-efficient design)
    # 50+ tools → 12 powerful tools
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def page(action: str, url: Optional[str] = None, wait: bool = False) -> Dict:
        """Page navigation and info.

        Actions:
          - goto: Navigate to URL (requires url param)
          - reload: Reload page (wait=True to ignore cache)
          - back/forward: History navigation
          - info: Get current URL and title

        Returns: {url, title} or action result
        """
        b = get_browser()
        if action == "goto" and url:
            b.goto(url, wait=wait)
        elif action == "reload":
            b.reload(wait)  # wait param used as ignore_cache
        elif action == "back":
            b.back()
        elif action == "forward":
            b.forward()
        elif action == "info":
            pass
        else:
            return {"error": f"Unknown action: {action}"}
        return {"url": b.url, "title": b.title}

    @mcp.tool()
    def dom(selector: str, action: str = "text", attr: Optional[str] = None,
            value: Optional[str] = None) -> Any:
        """DOM query and manipulation.

        Actions:
          - text: Get text content (default)
          - html: Get innerHTML
          - outer: Get outerHTML
          - attr: Get attribute (requires attr param)
          - set_attr: Set attribute (requires attr and value)
          - value: Get input value
          - exists: Check if element exists
          - count: Count matching elements

        Returns: Query result or bool for mutations
        """
        b = get_browser()
        if action == "text":
            return b.text(selector)
        elif action == "html":
            return b.html(selector)
        elif action == "outer":
            return b.outer_html(selector)
        elif action == "attr" and attr:
            return b.attr(selector, attr)
        elif action == "set_attr" and attr and value is not None:
            return b.set_attr(selector, attr, value)
        elif action == "value":
            return b.value(selector)
        elif action == "exists":
            return b.query(selector)
        elif action == "count":
            return b.query_all(selector)
        return {"error": f"Unknown action: {action}"}

    @mcp.tool()
    def interact(selector: str, action: str = "click", text: Optional[str] = None,
                 clear: bool = True) -> bool:
        """Element interaction.

        Actions:
          - click: Click element (default)
          - type: Type text (requires text param, clear=True clears first)
          - focus: Focus element
          - select: Select dropdown option (text=option value)
          - check/uncheck: Checkbox control
          - scroll: Scroll element into view

        Returns: Success bool
        """
        b = get_browser()
        if action == "click":
            return b.click(selector)
        elif action == "type" and text is not None:
            return b.type(selector, text, clear)
        elif action == "focus":
            return b.focus(selector)
        elif action == "select" and text:
            return b.select(selector, text)
        elif action == "check":
            return b.check(selector, True)
        elif action == "uncheck":
            return b.check(selector, False)
        elif action == "scroll":
            return b.scroll_into_view(selector)
        return False

    @mcp.tool()
    def wait(target: str, timeout: int = 30, type: str = "selector") -> bool:
        """Wait for conditions.

        Types:
          - selector: Wait for element to appear (default)
          - gone: Wait for element to disappear
          - text: Wait for text on page

        Returns: True if condition met, False if timeout
        """
        b = get_browser()
        if type == "selector":
            return b.wait(target, timeout)
        elif type == "gone":
            return b.wait_gone(target, timeout)
        elif type == "text":
            return b.wait_text(target, timeout)
        return False

    @mcp.tool()
    def js(script: str, timeout: int = 30) -> Any:
        """Execute JavaScript and return result."""
        return get_browser().eval(script, timeout)

    @mcp.tool()
    def capture(type: str = "screenshot", path: Optional[str] = None,
                full_page: bool = False, selector: Optional[str] = None) -> str:
        """Capture screenshot or PDF.

        Types: screenshot (default), pdf

        Returns: Base64 data or "Saved to {path}" if path given
        """
        b = get_browser()
        if type == "pdf":
            data = b.pdf(path)
        else:
            data = b.screenshot(path, full_page, selector)
        if path:
            return f"Saved to {path}"
        return base64.b64encode(data).decode()

    @mcp.tool()
    def tabs(action: str = "list", url: Optional[str] = None,
             page_id: Optional[str] = None) -> Any:
        """Tab/page management.

        Actions:
          - list: List all tabs (default)
          - new: Open new tab (url param)
          - close: Close tab (page_id param)
          - switch: Switch to tab (page_id param)

        Returns: Tab list or action result
        """
        b = get_browser()
        if action == "list":
            return b.pages()
        elif action == "new":
            return b.new_page(url or "about:blank")
        elif action == "close" and page_id:
            return b.close_page(page_id)
        elif action == "switch" and page_id:
            return b.switch_page(page_id) if hasattr(b, 'switch_page') else {"error": "Not supported"}
        return {"error": f"Unknown action: {action}"}

    @mcp.tool()
    def input(action: str, x: int = 0, y: int = 0, key: Optional[str] = None,
              text: Optional[str] = None, button: str = "left") -> bool:
        """Low-level input events.

        Actions:
          - click: Mouse click at x,y (button: left/right/middle)
          - move: Move mouse to x,y
          - wheel: Scroll at x,y (use y for scroll amount)
          - key: Press key (requires key param, e.g. "Enter", "Ctrl+A")
          - type: Type text character by character

        Returns: Success bool
        """
        b = get_browser()
        if action == "click":
            b.mouse_click(x, y, button, 1)
        elif action == "dblclick":
            b.mouse_click(x, y, button, 2)
        elif action == "move":
            b.mouse_move(x, y)
        elif action == "wheel":
            b.mouse_wheel(x, y, 0, y)  # y doubles as delta_y for simplicity
        elif action == "key" and key:
            b.key_press(key)
        elif action == "type" and text:
            b.key_type(text)
        else:
            return False
        return True

    @mcp.tool()
    def storage(action: str, key: Optional[str] = None, value: Optional[str] = None,
                type: str = "cookie", domain: Optional[str] = None) -> Any:
        """Browser storage management (cookies, localStorage, sessionStorage).

        Types: cookie (default), local, session

        Actions:
          - get: Get value(s). For cookies: returns all if no key
          - set: Set value (requires key, value)
          - delete: Delete by key
          - clear: Clear all

        Returns: Value(s) or success bool
        """
        b = get_browser()
        is_local = type == "local"

        if type == "cookie":
            if action == "get":
                return b.cookies()
            elif action == "set" and key and value:
                return b.set_cookie(key, value, domain)
            elif action == "delete" and key:
                b.delete_cookies(key, domain)
                return True
            elif action == "clear":
                b.clear_cookies()
                return True
        else:  # localStorage or sessionStorage
            if action == "get" and key:
                return b.storage_get(key, is_local)
            elif action == "set" and key and value:
                b.storage_set(key, value, is_local)
                return True
            elif action == "delete" and key:
                b.storage_remove(key, is_local)
                return True
            elif action == "clear":
                b.storage_clear(is_local)
                return True
        return {"error": f"Invalid action/params for {type}"}

    @mcp.tool()
    def fetch(url: str, method: str = "GET", body: Optional[Dict] = None,
              headers: Optional[Dict] = None) -> Any:
        """HTTP request through browser (uses cookies, bypasses CORS)."""
        return get_browser().fetch(url, method, body, headers)

    @mcp.tool()
    def emulate(viewport: Optional[Dict] = None, user_agent: Optional[str] = None,
                geolocation: Optional[Dict] = None, timezone: Optional[str] = None,
                offline: Optional[bool] = None) -> bool:
        """Device/environment emulation. Only provided params are applied.

        Args:
          viewport: {width, height, scale?, mobile?}
          user_agent: UA string
          geolocation: {lat, lon, accuracy?}
          timezone: e.g. "Asia/Seoul"
          offline: True/False

        Returns: Success bool
        """
        b = get_browser()
        if viewport:
            b.viewport(viewport.get("width", 1280), viewport.get("height", 720),
                      viewport.get("scale", 1.0), viewport.get("mobile", False))
        if user_agent:
            b.user_agent(user_agent)
        if geolocation:
            b.geolocation(geolocation["lat"], geolocation["lon"],
                         geolocation.get("accuracy", 100))
        if timezone:
            b.timezone(timezone)
        if offline is not None:
            b.offline(offline)
        return True

    @mcp.tool()
    def file(action: str, path: str, url: Optional[str] = None,
             selector: Optional[str] = None, content: Optional[str] = None) -> Dict:
        """File upload/download operations.

        Actions:
          - download: Download file from URL to path
          - upload: Upload file to input element (requires selector)
          - read: Read file and return content (text or base64)
          - write: Write content to file

        Returns: {success: bool, path: str, size?: int, error?: str}
        """
        import os
        from pathlib import Path as P

        b = get_browser()
        result = {"success": False, "path": path}

        try:
            if action == "download" and url:
                # Download via browser fetch
                script = f'''
                (async () => {{
                    const response = await fetch("{url}");
                    const blob = await response.blob();
                    const buffer = await blob.arrayBuffer();
                    return Array.from(new Uint8Array(buffer));
                }})()
                '''
                data = b.eval(script, timeout=60)
                with open(path, 'wb') as f:
                    f.write(bytes(data))
                result["success"] = True
                result["size"] = len(data)

            elif action == "upload" and selector:
                # Use CDP to set file input
                # This requires the file to exist on the PC running the browser
                node_id = b.cdp.send("DOM.querySelector",
                                    nodeId=b.cdp.send("DOM.getDocument")["root"]["nodeId"],
                                    selector=selector)["nodeId"]
                b.cdp.send("DOM.setFileInputFiles", nodeId=node_id, files=[path])
                result["success"] = True

            elif action == "read":
                p = P(path)
                if p.exists():
                    # Try text first, fallback to base64
                    try:
                        result["content"] = p.read_text()
                        result["type"] = "text"
                    except UnicodeDecodeError:
                        result["content"] = base64.b64encode(p.read_bytes()).decode()
                        result["type"] = "base64"
                    result["success"] = True
                    result["size"] = p.stat().st_size
                else:
                    result["error"] = "File not found"

            elif action == "write" and content is not None:
                p = P(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                # Check if content is base64
                if content.startswith("base64:"):
                    p.write_bytes(base64.b64decode(content[7:]))
                else:
                    p.write_text(content)
                result["success"] = True
                result["size"] = p.stat().st_size

            else:
                result["error"] = f"Invalid action or missing params: {action}"

        except Exception as e:
            result["error"] = str(e)

        return result

    @mcp.tool()
    def debug(action: str = "console", selector: Optional[str] = None,
              timeout: float = 1.0) -> Any:
        """Debugging utilities.

        Actions:
          - console: Get console messages
          - network: Get network requests (call once to enable, again to get)
          - highlight: Highlight element (requires selector)
          - unhighlight: Remove highlight
          - a11y: Get accessibility tree
          - metrics: Get performance metrics
          - dialog: Handle JS dialog (selector="accept" or "dismiss", text for prompt)

        Returns: Action-specific data
        """
        b = get_browser()
        if action == "console":
            b.console_enable()
            return b.console_messages(timeout)
        elif action == "network":
            b.network_enable()
            return b.network_requests(timeout)
        elif action == "highlight" and selector:
            b.highlight(selector)
            return True
        elif action == "unhighlight":
            b.hide_highlight()
            return True
        elif action == "a11y":
            return b.accessibility_tree()
        elif action == "metrics":
            return b.performance_metrics()
        elif action == "dialog":
            accept = selector != "dismiss"
            text = None if selector in ["accept", "dismiss"] else selector
            b.dialog_handle(accept, text)
            return True
        return {"error": f"Unknown action: {action}"}

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
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse, Response
    from starlette.requests import Request
    from starlette.types import ASGIApp, Receive, Scope, Send
    from mcp.server.sse import SseServerTransport
    from mcp.server.transport_security import TransportSecuritySettings

    import re
    # UUID pattern for session validation
    SESSION_ID_PATTERN = re.compile(r'^[a-f0-9]{32}$')

    # Create SSE transport with disabled DNS rebinding (we use token auth)
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    sse_transport = SseServerTransport("/messages/", security_settings=security_settings)

    # Track sessions for persistence
    known_sessions: Dict[str, bool] = {}  # session_id -> initialized

    async def handle_sse(request: Request):
        """Handle SSE connection with session tracking."""
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            # Extract session ID from the endpoint message
            # The session ID is generated inside connect_sse, we need to track it
            read_stream, write_stream = streams

            # Run the MCP server
            await mcp._mcp_server.run(
                read_stream,
                write_stream,
                mcp._mcp_server.create_initialization_options()
            )
        return Response()

    async def handle_messages(request: Request):
        """Handle POST messages with session recovery."""
        session_id = request.query_params.get("session_id", "")

        # Check if session exists in SSE transport
        try:
            session_uuid = UUID(hex=session_id)
            if session_uuid not in sse_transport._read_stream_writers:
                # Session is dead - return helpful error
                return Response(
                    content='{"jsonrpc":"2.0","error":{"code":-32000,"message":"Session expired. Please reconnect SSE."},"id":null}',
                    status_code=410,  # Gone
                    media_type="application/json"
                )
        except (ValueError, AttributeError):
            pass

        return await sse_transport.handle_post_message(
            request.scope, request.receive, request._send
        )

    # Build Starlette app with routes
    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Route("/messages/", endpoint=handle_messages, methods=["POST"]),
    ]

    async def lifespan(app):
        print("[*] SSE server starting with session persistence...", file=sys.stderr)
        yield
        print("[*] SSE server shutting down...", file=sys.stderr)

    starlette_app = Starlette(routes=routes, lifespan=lifespan)

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

    # Wrap with auth middleware
    app = AuthMiddleware(starlette_app)

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
