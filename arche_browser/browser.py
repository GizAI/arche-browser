"""
Browser automation via Chrome DevTools Protocol.

Usage:
    from arche_browser import Browser

    with Browser() as b:
        b.goto("https://example.com")
        print(b.title)
        b.screenshot("page.png")
"""

import json
import time
import base64
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

import websocket
import requests


# ═══════════════════════════════════════════════════════════════════
# CDP Transport
# ═══════════════════════════════════════════════════════════════════

class CDP:
    """Chrome DevTools Protocol connection."""

    def __init__(self, address: str = "localhost:9222"):
        self.address = address
        self._ws: Optional[websocket.WebSocket] = None
        self._id = 0
        self._callbacks: Dict[str, List[Callable]] = {}
        self._base: Optional[str] = None

    def connect(self, page_filter: Optional[Callable[[str], bool]] = None) -> "CDP":
        """Connect to a browser page."""
        if self._ws:
            return self

        pages = requests.get(f"http://{self.address}/json/list", timeout=10).json()

        # Find matching page (skip extensions and devtools)
        page = None
        for p in pages:
            url = p.get("url", "")
            ptype = p.get("type", "")

            # Skip non-page types
            if ptype != "page":
                continue
            # Skip extensions and devtools
            if url.startswith("chrome-extension://") or url.startswith("devtools://"):
                continue

            if page_filter and page_filter(url):
                page = p
                break
            elif not page_filter:
                page = p
                break

        # Fallback to first page if no regular page found
        if not page and pages:
            for p in pages:
                if p.get("type") == "page":
                    page = p
                    break

        if not page:
            raise ConnectionError("No browser page found")

        self._base = "/".join(page.get("url", "").split("/")[:3])
        ws_url = page.get("webSocketDebuggerUrl")
        self._ws = websocket.create_connection(ws_url, timeout=60)
        return self

    def send(self, method: str, params: Optional[Dict] = None) -> Dict:
        """Send CDP command and return result."""
        if not self._ws:
            self.connect()

        self._id += 1
        msg = {"id": self._id, "method": method}
        if params:
            msg["params"] = params
        self._ws.send(json.dumps(msg))

        # Wait for response, dispatch events
        for _ in range(200):
            result = json.loads(self._ws.recv())

            if "method" in result:
                event = result["method"]
                if event in self._callbacks:
                    for cb in self._callbacks[event]:
                        cb(result.get("params", {}))
                continue

            if result.get("id") == self._id:
                if "error" in result:
                    raise RuntimeError(f"CDP: {result['error']}")
                return result.get("result", {})
        return {}

    def on(self, event: str, callback: Callable[[Dict], None]):
        """Subscribe to CDP event."""
        self._callbacks.setdefault(event, []).append(callback)

    def poll(self, timeout: float = 0.1) -> List[Dict]:
        """Poll for events without blocking."""
        if not self._ws:
            return []

        events = []
        self._ws.settimeout(timeout)
        try:
            while True:
                result = json.loads(self._ws.recv())
                if "method" in result:
                    event = result["method"]
                    params = result.get("params", {})
                    events.append({"event": event, "params": params})
                    if event in self._callbacks:
                        for cb in self._callbacks[event]:
                            cb(params)
        except:
            pass
        self._ws.settimeout(60)
        return events

    def close(self):
        """Close connection."""
        if self._ws:
            try:
                self._ws.close()
            except:
                pass
            self._ws = None


# ═══════════════════════════════════════════════════════════════════
# Browser
# ═══════════════════════════════════════════════════════════════════

class Browser:
    """
    Full-featured browser automation.

    Provides high-level API for:
    - Navigation and JavaScript execution
    - DOM manipulation and form filling
    - Screenshots and PDF generation
    - Cookie and storage management
    - Network monitoring and interception
    - Device emulation
    - Console and performance monitoring
    """

    def __init__(self, address: str = "localhost:9222"):
        self.cdp = CDP(address)
        self.cdp.connect()
        self.cdp.send("Runtime.enable")
        self.cdp.send("Page.enable")

    def close(self):
        self.cdp.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ─── JavaScript ─────────────────────────────────────────────────

    def eval(self, script: str, timeout: int = 30) -> Any:
        """Execute JavaScript and return result."""
        result = self.cdp.send("Runtime.evaluate", {
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

    def call(self, fn: str, *args) -> Any:
        """Call JavaScript function with arguments."""
        return self.eval(f"({fn})(...{json.dumps(args)})")

    # ─── Navigation ─────────────────────────────────────────────────

    def goto(self, url: str, wait: bool = True) -> "Browser":
        """Navigate to URL."""
        self.cdp.send("Page.navigate", {"url": url})
        if wait:
            time.sleep(0.5)
            self.wait_load()
        self.cdp._base = "/".join(url.split("/")[:3])
        return self

    def reload(self, ignore_cache: bool = False) -> "Browser":
        """Reload page."""
        self.cdp.send("Page.reload", {"ignoreCache": ignore_cache})
        return self

    def back(self) -> "Browser":
        """Go back in history."""
        self.eval("history.back()")
        return self

    def forward(self) -> "Browser":
        """Go forward in history."""
        self.eval("history.forward()")
        return self

    def wait_load(self, timeout: int = 30) -> bool:
        """Wait for page load."""
        end = time.time() + timeout
        while time.time() < end:
            state = self.eval("document.readyState")
            if state == "complete":
                return True
            time.sleep(0.2)
        return False

    @property
    def url(self) -> str:
        return self.eval("location.href") or ""

    @property
    def title(self) -> str:
        return self.eval("document.title") or ""

    # ─── HTTP via Browser ───────────────────────────────────────────

    def fetch(self, path: str, method: str = "GET",
              body: Optional[Dict] = None, headers: Optional[Dict] = None,
              base: Optional[str] = None) -> Any:
        """Fetch via browser (uses cookies, bypasses CORS)."""
        url = (base or self.cdp._base or "") + path
        opts = {"method": method, "credentials": "include", "headers": headers or {}}
        if body:
            opts["body"] = json.dumps(body)
            opts["headers"]["Content-Type"] = opts["headers"].get("Content-Type", "application/json")

        return self.eval(f"""
            (async () => {{
                const r = await fetch({json.dumps(url)}, {json.dumps(opts)});
                const t = await r.text();
                try {{ return JSON.stringify(JSON.parse(t)); }} catch {{ return t; }}
            }})()
        """)

    def get(self, path: str, **kw) -> Any:
        return self.fetch(path, "GET", **kw)

    def post(self, path: str, body: Dict = None, **kw) -> Any:
        return self.fetch(path, "POST", body, **kw)

    def patch(self, path: str, body: Dict, **kw) -> Any:
        return self.fetch(path, "PATCH", body, **kw)

    def delete(self, path: str, **kw) -> Any:
        return self.fetch(path, "DELETE", **kw)

    # ─── DOM ────────────────────────────────────────────────────────

    def query(self, selector: str) -> bool:
        """Check if element exists."""
        return bool(self.eval(f"!!document.querySelector({json.dumps(selector)})"))

    def query_all(self, selector: str) -> int:
        """Count matching elements."""
        return self.eval(f"document.querySelectorAll({json.dumps(selector)}).length") or 0

    def text(self, selector: str = "body") -> str:
        """Get element text."""
        return self.eval(f"document.querySelector({json.dumps(selector)})?.innerText") or ""

    def html(self, selector: str = "html") -> str:
        """Get element HTML."""
        return self.eval(f"document.querySelector({json.dumps(selector)})?.innerHTML") or ""

    def outer_html(self, selector: str = "html") -> str:
        """Get element outer HTML."""
        return self.eval(f"document.querySelector({json.dumps(selector)})?.outerHTML") or ""

    def attr(self, selector: str, name: str) -> Optional[str]:
        """Get element attribute."""
        return self.eval(f"document.querySelector({json.dumps(selector)})?.getAttribute({json.dumps(name)})")

    def set_attr(self, selector: str, name: str, value: str) -> bool:
        """Set element attribute."""
        return bool(self.eval(f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return false;
                el.setAttribute({json.dumps(name)}, {json.dumps(value)});
                return true;
            }})()
        """))

    def value(self, selector: str) -> Optional[str]:
        """Get input value."""
        return self.eval(f"document.querySelector({json.dumps(selector)})?.value")

    # ─── Input ──────────────────────────────────────────────────────

    def type(self, selector: str, text: str, clear: bool = True) -> bool:
        """Type into input element."""
        return bool(self.eval(f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return false;
                el.focus();
                if ({json.dumps(clear)}) el.value = '';
                el.value += {json.dumps(text)};
                el.dispatchEvent(new InputEvent('input', {{bubbles: true, data: {json.dumps(text)}}}));
                return true;
            }})()
        """))

    def click(self, selector: str) -> bool:
        """Click element."""
        return bool(self.eval(f"document.querySelector({json.dumps(selector)})?.click() || true"))

    def focus(self, selector: str) -> bool:
        """Focus element."""
        return bool(self.eval(f"document.querySelector({json.dumps(selector)})?.focus() || true"))

    def blur(self, selector: str) -> bool:
        """Blur element."""
        return bool(self.eval(f"document.querySelector({json.dumps(selector)})?.blur() || true"))

    def scroll(self, x: int = 0, y: int = 0, selector: Optional[str] = None) -> "Browser":
        """Scroll page or element."""
        if selector:
            self.eval(f"document.querySelector({json.dumps(selector)})?.scrollTo({x}, {y})")
        else:
            self.eval(f"window.scrollTo({x}, {y})")
        return self

    def scroll_into_view(self, selector: str) -> bool:
        """Scroll element into view."""
        return bool(self.eval(f"document.querySelector({json.dumps(selector)})?.scrollIntoView() || true"))

    def select(self, selector: str, value: str) -> bool:
        """Select option in dropdown."""
        return bool(self.eval(f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return false;
                el.value = {json.dumps(value)};
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }})()
        """))

    def check(self, selector: str, checked: bool = True) -> bool:
        """Check/uncheck checkbox."""
        return bool(self.eval(f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return false;
                el.checked = {json.dumps(checked)};
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }})()
        """))

    # ─── Waiting ────────────────────────────────────────────────────

    def wait(self, selector: str, timeout: int = 30) -> bool:
        """Wait for element to appear."""
        end = time.time() + timeout
        while time.time() < end:
            if self.query(selector):
                return True
            time.sleep(0.2)
        return False

    def wait_gone(self, selector: str, timeout: int = 30) -> bool:
        """Wait for element to disappear."""
        end = time.time() + timeout
        while time.time() < end:
            if not self.query(selector):
                return True
            time.sleep(0.2)
        return False

    def wait_text(self, text: str, timeout: int = 30) -> bool:
        """Wait for text on page."""
        end = time.time() + timeout
        while time.time() < end:
            if text in self.text():
                return True
            time.sleep(0.2)
        return False

    def sleep(self, seconds: float) -> "Browser":
        """Sleep."""
        time.sleep(seconds)
        return self

    # ─── Cookies ────────────────────────────────────────────────────

    def cookies(self, urls: Optional[List[str]] = None) -> List[Dict]:
        """Get cookies."""
        params = {"urls": urls} if urls else {}
        return self.cdp.send("Network.getCookies", params).get("cookies", [])

    def set_cookie(self, name: str, value: str, domain: Optional[str] = None, **kw) -> bool:
        """Set cookie."""
        params = {"name": name, "value": value, **kw}
        if domain:
            params["domain"] = domain
        return self.cdp.send("Network.setCookie", params).get("success", False)

    def delete_cookies(self, name: str, domain: Optional[str] = None) -> "Browser":
        """Delete cookies by name."""
        params = {"name": name}
        if domain:
            params["domain"] = domain
        self.cdp.send("Network.deleteCookies", params)
        return self

    def clear_cookies(self) -> "Browser":
        """Clear all cookies."""
        self.cdp.send("Network.clearBrowserCookies")
        return self

    # ─── Storage ────────────────────────────────────────────────────

    def storage_get(self, key: str, local: bool = True) -> Optional[str]:
        """Get storage item."""
        store = "localStorage" if local else "sessionStorage"
        return self.eval(f"{store}.getItem({json.dumps(key)})")

    def storage_set(self, key: str, value: str, local: bool = True) -> "Browser":
        """Set storage item."""
        store = "localStorage" if local else "sessionStorage"
        self.eval(f"{store}.setItem({json.dumps(key)}, {json.dumps(value)})")
        return self

    def storage_remove(self, key: str, local: bool = True) -> "Browser":
        """Remove storage item."""
        store = "localStorage" if local else "sessionStorage"
        self.eval(f"{store}.removeItem({json.dumps(key)})")
        return self

    def storage_clear(self, local: bool = True) -> "Browser":
        """Clear storage."""
        store = "localStorage" if local else "sessionStorage"
        self.eval(f"{store}.clear()")
        return self

    # ─── Screenshots & PDF ──────────────────────────────────────────

    def screenshot(self, path: Optional[str] = None, full_page: bool = False,
                   selector: Optional[str] = None, format: str = "png", quality: int = 80) -> bytes:
        """Take screenshot."""
        params = {"format": format}
        if format == "jpeg":
            params["quality"] = quality

        if full_page:
            metrics = self.cdp.send("Page.getLayoutMetrics")
            params["clip"] = {
                "x": 0, "y": 0,
                "width": metrics["contentSize"]["width"],
                "height": metrics["contentSize"]["height"],
                "scale": 1
            }
        elif selector:
            box = self.eval(f"""
                (() => {{
                    const el = document.querySelector({json.dumps(selector)});
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {{x: r.x, y: r.y, width: r.width, height: r.height}};
                }})()
            """)
            if box:
                params["clip"] = {**box, "scale": 1}

        result = self.cdp.send("Page.captureScreenshot", params)
        data = base64.b64decode(result.get("data", ""))

        if path:
            with open(path, "wb") as f:
                f.write(data)
        return data

    def pdf(self, path: Optional[str] = None, **options) -> bytes:
        """Generate PDF (headless only)."""
        defaults = {"printBackground": True, "preferCSSPageSize": True}
        result = self.cdp.send("Page.printToPDF", {**defaults, **options})
        data = base64.b64decode(result.get("data", ""))

        if path:
            with open(path, "wb") as f:
                f.write(data)
        return data

    # ─── Console ────────────────────────────────────────────────────

    def console_enable(self) -> "Browser":
        """Enable console monitoring."""
        self.cdp.send("Runtime.enable")
        self.cdp.send("Log.enable")
        return self

    def console_messages(self, timeout: float = 1.0) -> List[Dict]:
        """Get console messages."""
        messages = []

        def on_console(params):
            args = params.get("args", [])
            text = " ".join(str(a.get("value", a.get("description", ""))) for a in args)
            messages.append({"type": params.get("type"), "text": text})

        def on_log(params):
            entry = params.get("entry", {})
            messages.append({
                "type": entry.get("level"),
                "text": entry.get("text", ""),
                "url": entry.get("url")
            })

        self.cdp.on("Runtime.consoleAPICalled", on_console)
        self.cdp.on("Log.entryAdded", on_log)
        self.cdp.poll(timeout)
        return messages

    # ─── Network ────────────────────────────────────────────────────

    def network_enable(self) -> "Browser":
        """Enable network monitoring."""
        self.cdp.send("Network.enable")
        return self

    def network_disable(self) -> "Browser":
        """Disable network monitoring."""
        self.cdp.send("Network.disable")
        return self

    def network_requests(self, timeout: float = 1.0) -> List[Dict]:
        """Get network requests."""
        requests_list = []

        def on_request(params):
            req = params.get("request", {})
            requests_list.append({
                "id": params.get("requestId"),
                "url": req.get("url"),
                "method": req.get("method"),
                "type": params.get("type")
            })

        def on_response(params):
            resp = params.get("response", {})
            for r in requests_list:
                if r["id"] == params.get("requestId"):
                    r["status"] = resp.get("status")
                    r["mime"] = resp.get("mimeType")
                    break

        self.cdp.on("Network.requestWillBeSent", on_request)
        self.cdp.on("Network.responseReceived", on_response)
        self.cdp.poll(timeout)
        return requests_list

    def network_intercept(self, patterns: List[str], callback: Callable[[Dict], Optional[Dict]]) -> "Browser":
        """Intercept network requests."""
        self.cdp.send("Fetch.enable", {"patterns": [{"urlPattern": p} for p in patterns]})

        def on_request(params):
            result = callback(params)
            if result:
                self.cdp.send("Fetch.fulfillRequest", {"requestId": params["requestId"], **result})
            else:
                self.cdp.send("Fetch.continueRequest", {"requestId": params["requestId"]})

        self.cdp.on("Fetch.requestPaused", on_request)
        return self

    # ─── Emulation ──────────────────────────────────────────────────

    def viewport(self, width: int, height: int, scale: float = 1.0, mobile: bool = False) -> "Browser":
        """Set viewport size."""
        self.cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": scale, "mobile": mobile
        })
        return self

    def user_agent(self, ua: str) -> "Browser":
        """Set user agent."""
        self.cdp.send("Emulation.setUserAgentOverride", {"userAgent": ua})
        return self

    def geolocation(self, lat: float, lon: float, accuracy: float = 100) -> "Browser":
        """Set geolocation."""
        self.cdp.send("Emulation.setGeolocationOverride", {
            "latitude": lat, "longitude": lon, "accuracy": accuracy
        })
        return self

    def timezone(self, tz: str) -> "Browser":
        """Set timezone (e.g., 'Asia/Seoul')."""
        self.cdp.send("Emulation.setTimezoneOverride", {"timezoneId": tz})
        return self

    def locale(self, locale: str) -> "Browser":
        """Set locale (e.g., 'ko-KR')."""
        self.cdp.send("Emulation.setLocaleOverride", {"locale": locale})
        return self

    def offline(self, offline: bool = True) -> "Browser":
        """Set offline mode."""
        self.cdp.send("Network.emulateNetworkConditions", {
            "offline": offline, "latency": 0,
            "downloadThroughput": -1, "uploadThroughput": -1
        })
        return self

    def throttle(self, download: int = -1, upload: int = -1, latency: int = 0) -> "Browser":
        """Throttle network (bytes/sec, -1 for unlimited)."""
        self.cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": latency,
            "downloadThroughput": download, "uploadThroughput": upload
        })
        return self

    # ─── Input Events ───────────────────────────────────────────────

    def mouse_move(self, x: int, y: int) -> "Browser":
        """Move mouse."""
        self.cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        return self

    def mouse_click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> "Browser":
        """Click at coordinates."""
        for _ in range(clicks):
            self.cdp.send("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": x, "y": y, "button": button, "clickCount": 1
            })
            self.cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": x, "y": y, "button": button, "clickCount": 1
            })
        return self

    def mouse_wheel(self, x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> "Browser":
        """Scroll with mouse wheel."""
        self.cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": x, "y": y, "deltaX": delta_x, "deltaY": delta_y
        })
        return self

    def key_press(self, key: str, modifiers: int = 0) -> "Browser":
        """Press key."""
        self.cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "modifiers": modifiers})
        self.cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "modifiers": modifiers})
        return self

    def key_type(self, text: str) -> "Browser":
        """Type text via keyboard events."""
        for char in text:
            self.cdp.send("Input.dispatchKeyEvent", {"type": "char", "text": char})
        return self

    # ─── Dialogs ────────────────────────────────────────────────────

    def dialog_handle(self, accept: bool = True, text: Optional[str] = None) -> "Browser":
        """Handle JavaScript dialog."""
        params = {"accept": accept}
        if text:
            params["promptText"] = text
        self.cdp.send("Page.handleJavaScriptDialog", params)
        return self

    # ─── Frames ─────────────────────────────────────────────────────

    def frames(self) -> List[Dict]:
        """Get all frames."""
        tree = self.cdp.send("Page.getFrameTree")

        def extract(node):
            frame = node.get("frame", {})
            result = [{"id": frame.get("id"), "url": frame.get("url"), "name": frame.get("name")}]
            for child in node.get("childFrames", []):
                result.extend(extract(child))
            return result

        return extract(tree.get("frameTree", {}))

    # ─── Performance ────────────────────────────────────────────────

    def performance_metrics(self) -> Dict[str, float]:
        """Get performance metrics."""
        result = self.cdp.send("Performance.getMetrics")
        return {m["name"]: m["value"] for m in result.get("metrics", [])}

    def tracing_start(self, categories: str = "-*,devtools.timeline") -> "Browser":
        """Start tracing."""
        self.cdp.send("Tracing.start", {"categories": categories})
        return self

    def tracing_stop(self) -> List[Dict]:
        """Stop tracing and return events."""
        events = []
        self.cdp.on("Tracing.dataCollected", lambda p: events.extend(p.get("value", [])))
        self.cdp.send("Tracing.end")
        self.cdp.poll(2.0)
        return events

    # ─── DOM Debugging ──────────────────────────────────────────────

    def highlight(self, selector: str) -> "Browser":
        """Highlight element."""
        node_id = self.cdp.send("DOM.querySelector", {
            "nodeId": self.cdp.send("DOM.getDocument")["root"]["nodeId"],
            "selector": selector
        }).get("nodeId")

        if node_id:
            self.cdp.send("Overlay.highlightNode", {
                "nodeId": node_id,
                "highlightConfig": {
                    "showInfo": True,
                    "contentColor": {"r": 111, "g": 168, "b": 220, "a": 0.66},
                    "paddingColor": {"r": 147, "g": 196, "b": 125, "a": 0.55},
                    "borderColor": {"r": 255, "g": 229, "b": 153, "a": 0.66},
                    "marginColor": {"r": 246, "g": 178, "b": 107, "a": 0.66}
                }
            })
        return self

    def hide_highlight(self) -> "Browser":
        """Hide highlight."""
        self.cdp.send("Overlay.hideHighlight")
        return self

    # ─── Accessibility ──────────────────────────────────────────────

    def accessibility_tree(self) -> Dict:
        """Get accessibility tree."""
        return self.cdp.send("Accessibility.getFullAXTree")

    # ─── Profiling ──────────────────────────────────────────────────

    def heap_snapshot(self, path: Optional[str] = None) -> str:
        """Take heap snapshot."""
        chunks = []
        self.cdp.on("HeapProfiler.addHeapSnapshotChunk", lambda p: chunks.append(p.get("chunk", "")))
        self.cdp.send("HeapProfiler.takeHeapSnapshot")
        self.cdp.poll(5.0)

        snapshot = "".join(chunks)
        if path:
            with open(path, "w") as f:
                f.write(snapshot)
        return snapshot

    # ─── Pages ──────────────────────────────────────────────────────

    def pages(self) -> List[Dict]:
        """List all browser pages."""
        return requests.get(f"http://{self.cdp.address}/json/list", timeout=10).json()

    def new_page(self, url: str = "about:blank") -> Dict:
        """Create new page."""
        return requests.put(f"http://{self.cdp.address}/json/new?{url}", timeout=10).json()

    def close_page(self, page_id: str) -> bool:
        """Close page."""
        resp = requests.get(f"http://{self.cdp.address}/json/close/{page_id}", timeout=10)
        return resp.text == "Target is closing"

    def activate_page(self, page_id: str) -> bool:
        """Activate page."""
        resp = requests.get(f"http://{self.cdp.address}/json/activate/{page_id}", timeout=10)
        return resp.status_code == 200
