"""
MCP Server for browser automation.

Exposes all browser functionality as MCP tools.
"""

import sys
import base64
import atexit
from typing import Any, Dict, List, Optional

from .chrome import Chrome
from .browser import Browser
from .auth import TokenAuth, create_auth_middleware


# Global state
_chrome: Optional[Chrome] = None
_browser: Optional[Browser] = None
_auth: Optional[TokenAuth] = None


def get_browser() -> Browser:
    """Get or create browser instance."""
    global _chrome, _browser

    if _browser is None or _browser.cdp._ws is None:
        if _chrome is None:
            _chrome = Chrome()
            _chrome.start()
        _browser = Browser(f"localhost:{_chrome.port}")

    return _browser


def cleanup():
    """Cleanup on exit."""
    global _chrome, _browser
    if _browser:
        _browser.close()
        _browser = None
    if _chrome:
        _chrome.stop()
        _chrome = None


atexit.register(cleanup)


def create_server(headless: bool = False, local_control: bool = False, browser_tools: bool = True):
    """Create MCP server with all browser tools.

    Args:
        headless: Run Chrome in headless mode
        local_control: Enable full local PC control (shell, python, files, etc.)
        browser_tools: Enable browser automation tools (default: True)
    """
    from mcp.server.fastmcp import FastMCP

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

    mcp = FastMCP(
        name=name,
        instructions=". ".join(instructions)
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
    browser_tools: bool = True
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
    """
    global _auth

    mcp = create_server(headless, local_control, browser_tools)

    # Start browser immediately if browser tools are enabled
    if browser_tools:
        print(f"[*] Starting Chrome {'(headless)' if headless else '(visible)'}...", file=sys.stderr)
        try:
            browser = get_browser()
            print(f"[*] Chrome ready at localhost:{browser.cdp.address.split(':')[1]}", file=sys.stderr)
        except Exception as e:
            print(f"[!] Chrome failed to start: {e}", file=sys.stderr)
            print(f"[!] Browser tools will not be available", file=sys.stderr)

    if transport == "sse":
        if auth:
            _auth = TokenAuth(token)
            auth_token = _auth.token

            print(f"[*] Arche Browser MCP Server (SSE)", file=sys.stderr)
            print(f"[*] Port: {port}", file=sys.stderr)
            print(f"[*] Auth: ENABLED", file=sys.stderr)
            print(f"[*] Token: {auth_token}", file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"[*] Connect URL:", file=sys.stderr)
            print(f"    http://localhost:{port}/sse?token={auth_token}", file=sys.stderr)
            print(f"", file=sys.stderr)
            print(f"[*] Claude Code MCP config:", file=sys.stderr)
            print(f'    {{"url": "http://HOST:{port}/sse?token={auth_token}"}}', file=sys.stderr)

            # Run with auth middleware
            run_sse_with_auth(mcp, port, _auth)
        else:
            print(f"[*] Arche Browser MCP Server (SSE)", file=sys.stderr)
            print(f"[*] Port: {port}", file=sys.stderr)
            print(f"[*] Auth: DISABLED (not recommended)", file=sys.stderr)
            print(f"[*] URL: http://localhost:{port}/sse", file=sys.stderr)
            mcp.settings.port = port
            mcp.run(transport="sse")
    else:
        print("[*] Arche Browser MCP Server (stdio)", file=sys.stderr)
        mcp.run()


def run_sse_with_auth(mcp, port: int, auth: TokenAuth):
    """Run SSE server with authentication middleware."""
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Check token from query param or header
            token = request.query_params.get("token", "")
            if not token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]

            if not auth.verify(token):
                return JSONResponse(
                    {"error": "Unauthorized - Invalid or missing token"},
                    status_code=401
                )

            return await call_next(request)

    # Get the SSE app from FastMCP and add auth middleware
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    app = mcp.sse_app()
    app.add_middleware(AuthMiddleware)

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
