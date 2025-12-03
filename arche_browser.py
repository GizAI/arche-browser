#!/usr/bin/env python3
"""
Arche Browser - MCP Server for Browser Automation

Install:
    pip install arche-browser

Run locally:
    arche-browser

Remote MCP (with SSE):
    arche-browser --sse --port 8080

Connect from Claude Code:
    Add to MCP settings: {"url": "http://your-ip:8080/sse"}
"""

import os
import sys
import json
import time
import base64
import socket
import signal
import shutil
import platform
import argparse
import subprocess
import threading
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

# ═══════════════════════════════════════════════════════════════════
# Chrome Management
# ═══════════════════════════════════════════════════════════════════

def find_chrome() -> str:
    """Find Chrome executable for current OS."""
    system = platform.system()

    if system == "Darwin":
        paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    elif system == "Windows":
        paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ]
    else:
        paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]
        for name in ["google-chrome", "chromium", "chromium-browser"]:
            path = shutil.which(name)
            if path:
                paths.insert(0, path)

    for path in paths:
        if os.path.exists(path):
            return path

    raise FileNotFoundError("Chrome not found")


class ChromeManager:
    """Manages Chrome browser lifecycle."""

    def __init__(self, port: int = 9222, headless: bool = False):
        self.port = port
        self.headless = headless
        self.process = None
        self.chrome_path = find_chrome()
        self.user_data_dir = os.path.join(os.path.expanduser("~"), ".arche-browser", "profile")

    def start(self, url: str = None):
        """Start Chrome with remote debugging."""
        os.makedirs(self.user_data_dir, exist_ok=True)

        args = [
            self.chrome_path,
            f"--remote-debugging-port={self.port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={self.user_data_dir}",
        ]

        if self.headless:
            args.append("--headless=new")

        if url:
            args.append(url)

        kwargs = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["preexec_fn"] = os.setsid

        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        self._wait_ready()
        return self

    def _wait_ready(self, timeout: int = 30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    s.connect(("127.0.0.1", self.port))
                    return
            except:
                time.sleep(0.2)
        raise TimeoutError("Chrome did not start")

    def stop(self):
        if self.process:
            if platform.system() == "Windows":
                self.process.terminate()
            else:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            self.process.wait(timeout=5)
            self.process = None


# ═══════════════════════════════════════════════════════════════════
# Browser Client (CDP)
# ═══════════════════════════════════════════════════════════════════

class Browser:
    """Browser automation via Chrome DevTools Protocol."""

    def __init__(self, port: int = 9222):
        self.port = port
        self._ws = None
        self._id = 0
        self._base = None

    def connect(self):
        import websocket
        import requests

        pages = requests.get(f"http://127.0.0.1:{self.port}/json/list", timeout=10).json()
        if not pages:
            raise ConnectionError("No pages found")

        page = pages[0]
        self._base = "/".join(page.get("url", "").split("/")[:3])
        ws_url = page.get("webSocketDebuggerUrl")

        self._ws = websocket.create_connection(ws_url, timeout=60)
        self._send("Runtime.enable")
        self._send("Page.enable")
        return self

    def _send(self, method: str, params: dict = None) -> dict:
        self._id += 1
        msg = {"id": self._id, "method": method}
        if params:
            msg["params"] = params
        self._ws.send(json.dumps(msg))

        for _ in range(200):
            result = json.loads(self._ws.recv())
            if result.get("id") == self._id:
                if "error" in result:
                    raise RuntimeError(f"CDP Error: {result['error']}")
                return result.get("result", {})
        return {}

    def eval(self, script: str, timeout: int = 30) -> Any:
        result = self._send("Runtime.evaluate", {
            "expression": script,
            "awaitPromise": True,
            "timeout": timeout * 1000,
            "returnByValue": True
        })
        if "result" in result:
            value = result["result"].get("value")
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except:
                    return value
            return value
        return None

    def goto(self, url: str) -> str:
        self._send("Page.navigate", {"url": url})
        self._base = "/".join(url.split("/")[:3])
        time.sleep(1)
        return self.url

    @property
    def url(self) -> str:
        return self.eval("location.href") or ""

    @property
    def title(self) -> str:
        return self.eval("document.title") or ""

    def text(self, selector: str = "body") -> str:
        return self.eval(f"document.querySelector({json.dumps(selector)})?.innerText") or ""

    def html(self, selector: str = "html") -> str:
        return self.eval(f"document.querySelector({json.dumps(selector)})?.outerHTML") or ""

    def click(self, selector: str) -> bool:
        return bool(self.eval(f"document.querySelector({json.dumps(selector)})?.click() || true"))

    def type(self, selector: str, text: str) -> bool:
        return bool(self.eval(f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return false;
                el.focus();
                el.value = {json.dumps(text)};
                el.dispatchEvent(new InputEvent('input', {{bubbles: true}}));
                return true;
            }})()
        """))

    def wait(self, selector: str, timeout: int = 30) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.eval(f"!!document.querySelector({json.dumps(selector)})"):
                return True
            time.sleep(0.2)
        return False

    def screenshot(self, path: str = None) -> bytes:
        result = self._send("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(result.get("data", ""))
        if path:
            with open(path, "wb") as f:
                f.write(data)
        return data

    def fetch(self, path: str, method: str = "GET", body: dict = None, headers: dict = None) -> Any:
        url = (self._base or "") + path
        opts = {"method": method, "credentials": "include", "headers": headers or {}}
        if body:
            opts["body"] = json.dumps(body)
            opts["headers"]["Content-Type"] = "application/json"
        return self.eval(f"""
            (async () => {{
                const r = await fetch({json.dumps(url)}, {json.dumps(opts)});
                const t = await r.text();
                try {{ return JSON.stringify(JSON.parse(t)); }} catch {{ return t; }}
            }})()
        """)

    def pages(self) -> List[Dict]:
        import requests
        return requests.get(f"http://127.0.0.1:{self.port}/json/list", timeout=10).json()

    def new_page(self, url: str = "about:blank") -> Dict:
        import requests
        return requests.put(f"http://127.0.0.1:{self.port}/json/new?{url}", timeout=10).json()

    def close(self):
        if self._ws:
            self._ws.close()
            self._ws = None


# ═══════════════════════════════════════════════════════════════════
# MCP Server
# ═══════════════════════════════════════════════════════════════════

# Global instances
chrome: Optional[ChromeManager] = None
browser: Optional[Browser] = None


def ensure_browser():
    """Ensure browser is running and connected."""
    global chrome, browser
    if browser is None or browser._ws is None:
        if chrome is None:
            chrome = ChromeManager()
            chrome.start()
        browser = Browser(chrome.port)
        browser.connect()
    return browser


def create_mcp_server():
    """Create FastMCP server with browser tools."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("arche-browser", description="Browser automation via Chrome DevTools Protocol")

    @mcp.tool()
    def browser_goto(url: str) -> str:
        """Navigate to URL. Returns the final URL after navigation."""
        b = ensure_browser()
        return b.goto(url)

    @mcp.tool()
    def browser_url() -> str:
        """Get current page URL."""
        b = ensure_browser()
        return b.url

    @mcp.tool()
    def browser_title() -> str:
        """Get current page title."""
        b = ensure_browser()
        return b.title

    @mcp.tool()
    def browser_text(selector: str = "body") -> str:
        """Get text content of element. Use 'body' for full page text."""
        b = ensure_browser()
        return b.text(selector)

    @mcp.tool()
    def browser_html(selector: str = "body") -> str:
        """Get HTML of element. Use 'body' for full page HTML."""
        b = ensure_browser()
        return b.html(selector)

    @mcp.tool()
    def browser_click(selector: str) -> bool:
        """Click an element by CSS selector."""
        b = ensure_browser()
        return b.click(selector)

    @mcp.tool()
    def browser_type(selector: str, text: str) -> bool:
        """Type text into an input element."""
        b = ensure_browser()
        return b.type(selector, text)

    @mcp.tool()
    def browser_wait(selector: str, timeout: int = 30) -> bool:
        """Wait for element to appear. Returns True if found."""
        b = ensure_browser()
        return b.wait(selector, timeout)

    @mcp.tool()
    def browser_eval(script: str) -> Any:
        """Execute JavaScript and return result."""
        b = ensure_browser()
        return b.eval(script)

    @mcp.tool()
    def browser_screenshot(path: str = None) -> str:
        """Take screenshot. Returns base64 if no path, otherwise saves to path."""
        b = ensure_browser()
        data = b.screenshot(path)
        if path:
            return f"Saved to {path}"
        return base64.b64encode(data).decode()

    @mcp.tool()
    def browser_fetch(path: str, method: str = "GET", body: dict = None, headers: dict = None) -> Any:
        """Make HTTP request through browser (uses cookies, bypasses CORS)."""
        b = ensure_browser()
        return b.fetch(path, method, body, headers)

    @mcp.tool()
    def browser_pages() -> List[Dict]:
        """List all open browser pages/tabs."""
        b = ensure_browser()
        return b.pages()

    @mcp.tool()
    def browser_new_page(url: str = "about:blank") -> Dict:
        """Open a new browser tab."""
        b = ensure_browser()
        return b.new_page(url)

    return mcp


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Arche Browser - MCP Server for Browser Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  arche-browser                    # Run as stdio MCP server
  arche-browser --sse --port 8080  # Run as SSE server for remote access
  arche-browser --headless         # Run headless

Remote connection (add to Claude Code MCP settings):
  {"url": "http://your-ip:8080/sse"}
        """
    )

    parser.add_argument("--sse", action="store_true", help="Run as SSE server for remote access")
    parser.add_argument("--port", type=int, default=8080, help="SSE server port (default: 8080)")
    parser.add_argument("--headless", action="store_true", help="Run Chrome in headless mode")
    parser.add_argument("--cdp-port", type=int, default=9222, help="Chrome CDP port (default: 9222)")

    args = parser.parse_args()

    # Set headless mode
    global chrome
    if args.headless:
        ChromeManager.headless = True

    mcp = create_mcp_server()

    def cleanup():
        global chrome, browser
        if browser:
            browser.close()
        if chrome:
            chrome.stop()

    import atexit
    atexit.register(cleanup)

    if args.sse:
        print(f"[*] Starting Arche Browser MCP Server (SSE mode)")
        print(f"[*] Port: {args.port}")
        print(f"[*] Connect URL: http://localhost:{args.port}/sse")
        print()
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        print("[*] Starting Arche Browser MCP Server (stdio mode)", file=sys.stderr)
        mcp.run()


if __name__ == "__main__":
    main()
