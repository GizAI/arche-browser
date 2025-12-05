"""
MCP Tool Definitions

All browser automation tools in one place.
Separated from server.py for clarity.
"""

import base64
from typing import Any, Dict, Optional

from .utils import box_center


def register_browser_tools(mcp, get_browser, get_context):
    """
    Register all browser automation tools.

    Args:
        mcp: FastMCP instance
        get_browser: Function to get Browser instance
        get_context: Function to get BrowserContext instance
    """

    # ═══════════════════════════════════════════════════════════════
    # CORE BROWSER TOOLS
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def page(action: str, url: Optional[str] = None, wait: bool = False) -> Dict:
        """Navigate: goto/reload/back/forward/info. Returns {url,title}."""
        b = get_browser()
        if action == "goto" and url:
            b.goto(url, wait=wait)
        elif action == "reload":
            b.reload(wait)
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
        """DOM query: text/html/outer/attr/value/exists/count. Use CSS selector."""
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
        """Interact via CSS selector: click/type/focus/select/check/scroll."""
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
        """Wait for: selector(default)/gone/text. Returns bool."""
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
        """Capture screenshot/pdf. Returns base64 or saves to path."""
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
        """Tabs: list/new/close/switch. Use page_id from list."""
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
        """Low-level: click/move/wheel at x,y. key/type for keyboard."""
        b = get_browser()
        if action == "click":
            b.mouse_click(x, y, button, 1)
        elif action == "dblclick":
            b.mouse_click(x, y, button, 2)
        elif action == "move":
            b.mouse_move(x, y)
        elif action == "wheel":
            b.mouse_wheel(x, y, 0, y)
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
        """Storage (cookie/local/session): get/set/delete/clear."""
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
        else:
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
        """Emulate viewport/user_agent/geolocation/timezone/offline."""
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
        """File: download/upload/read/write. Returns {success,path,size}."""
        from pathlib import Path as P

        b = get_browser()
        result = {"success": False, "path": path}

        try:
            if action == "download" and url:
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
                node_id = b.cdp.send("DOM.querySelector",
                                    nodeId=b.cdp.send("DOM.getDocument")["root"]["nodeId"],
                                    selector=selector)["nodeId"]
                b.cdp.send("DOM.setFileInputFiles", nodeId=node_id, files=[path])
                result["success"] = True

            elif action == "read":
                p = P(path)
                if p.exists():
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
        """Debug: console/network/highlight/a11y/metrics/dialog."""
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

    # ═══════════════════════════════════════════════════════════════
    # SNAPSHOT & UID-BASED TOOLS
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def snapshot(verbose: bool = False) -> str:
        """A11y snapshot with UIDs. Use UIDs for click/fill/focus/hover."""
        ctx = get_context()
        text, count = ctx.snapshot_mgr.take(verbose=verbose)
        b = get_browser()
        header = f"## {b.title}\nURL: {b.url}\nElements: {count}\n\n"
        return header + text

    @mcp.tool()
    def click(uid: str, double: bool = False) -> str:
        """Click element by UID. Returns updated snapshot."""
        ctx = get_context()
        mgr = ctx.snapshot_mgr

        if double:
            backend_id = mgr.get_element(uid)
            if not backend_id:
                return f"Error: Element '{uid}' not found"
            b = get_browser()
            box = b.cdp.send("DOM.getBoxModel", {"backendNodeId": backend_id})
            content = box.get("model", {}).get("content", [])
            center = box_center(content)
            if center:
                b.mouse_click(center[0], center[1], "left", 2)
            else:
                return f"Error: Cannot get element coordinates"
        else:
            mgr.click(uid)

        text, count = mgr.take()
        return f"Clicked [{uid}]\n\n{text}"

    @mcp.tool()
    def fill(uid: str, text: str, clear: bool = True) -> str:
        """Type into element by UID. Returns updated snapshot."""
        ctx = get_context()
        mgr = ctx.snapshot_mgr
        mgr.type_text(uid, text, clear)
        snap, count = mgr.take()
        return f"Typed into [{uid}]\n\n{snap}"

    @mcp.tool()
    def focus(uid: str) -> str:
        """Focus element by UID."""
        ctx = get_context()
        ctx.snapshot_mgr.focus(uid)
        return f"Focused [{uid}]"

    @mcp.tool()
    def hover(uid: str) -> str:
        """Hover element by UID. Returns updated snapshot."""
        ctx = get_context()
        mgr = ctx.snapshot_mgr
        backend_id = mgr.get_element(uid)
        if not backend_id:
            return f"Error: Element '{uid}' not found"

        b = get_browser()
        box = b.cdp.send("DOM.getBoxModel", {"backendNodeId": backend_id})
        content = box.get("model", {}).get("content", [])
        center = box_center(content)
        if center:
            b.mouse_move(center[0], center[1])
        else:
            return f"Error: Cannot get element coordinates"

        snap, _ = mgr.take()
        return f"Hovered [{uid}]\n\n{snap}"

    # ═══════════════════════════════════════════════════════════════
    # BROWSER HISTORY
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def history(
        action: str = "recent",
        query: str = "",
        max_results: int = 50,
        hours: int = 24,
        days: int = 30
    ) -> str:
        """Chrome history: recent/search/top/domains. Readonly sqlite."""
        try:
            from .history import BrowserHistory
            from .response import ResponseBuilder
        except ImportError as e:
            return f"Error: {e}"

        try:
            with BrowserHistory() as bh:
                if action == "recent":
                    items = bh.recent(hours=hours, max_results=max_results)
                elif action == "search":
                    items = bh.search(query=query, max_results=max_results)
                elif action == "top":
                    items = bh.most_visited(max_results=max_results, days=days)
                elif action == "domains":
                    domains = bh.domains(max_results=max_results, days=days)
                    lines = [f"Top domains (last {days} days):"]
                    for d in domains:
                        lines.append(f"  {d['visit_count']:4d} visits | {d['page_count']:3d} pages | {d['domain']}")
                    return "\n".join(lines)
                else:
                    return f"Unknown action: {action}"

                resp = ResponseBuilder.history(items, action)
                return resp.format()

        except FileNotFoundError as e:
            return f"History not found: {e}"
        except Exception as e:
            return f"Error reading history: {e}"

    # ═══════════════════════════════════════════════════════════════
    # NETWORK & CONSOLE COLLECTORS
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def network(
        action: str = "list",
        req_id: Optional[int] = None,
        types: Optional[str] = None,
        include_history: bool = False,
        page: int = 0,
        size: int = 50
    ) -> str:
        """Network requests: list/get. Collects across navigations."""
        ctx = get_context()
        nc = ctx.network

        if action == "get" and req_id:
            req = nc.get_by_id(req_id)
            if not req:
                return f"Request {req_id} not found"
            lines = [
                f"[{req.id}] {req.method} {req.url}",
                f"Status: {req.status or 'pending'} {req.status_text}",
                f"Type: {req.resource_type}",
            ]
            if req.error:
                lines.append(f"Error: {req.error}")
            if req.response_time and req.timestamp:
                lines.append(f"Duration: {(req.response_time - req.timestamp) * 1000:.0f}ms")
            if req.request_headers:
                lines.append("Request Headers:")
                for k, v in list(req.request_headers.items())[:10]:
                    lines.append(f"  {k}: {v[:50]}")
            if req.response_headers:
                lines.append("Response Headers:")
                for k, v in list(req.response_headers.items())[:10]:
                    lines.append(f"  {k}: {v[:50]}")
            return "\n".join(lines)

        type_list = types.split(",") if types else None
        requests = nc.get(include_history, type_list, page, size)

        lines = [f"Network Requests ({len(requests)} shown):"]
        for req in requests:
            status = req.status or "..."
            url = req.url[:60] + "..." if len(req.url) > 60 else req.url
            lines.append(f"  [{req.id}] {status} {req.method} {url}")

        return "\n".join(lines)

    @mcp.tool()
    def console(
        action: str = "list",
        msg_id: Optional[int] = None,
        types: Optional[str] = None,
        include_history: bool = False,
        page: int = 0,
        size: int = 50
    ) -> str:
        """Console messages: list/get/issues. Collects across navigations."""
        ctx = get_context()
        cc = ctx.console

        if action == "get" and msg_id:
            msg = cc.get_by_id(msg_id)
            if not msg:
                return f"Message {msg_id} not found"
            lines = [
                f"[{msg.id}] [{msg.type.upper()}] {msg.text}",
            ]
            if msg.url:
                lines.append(f"  at {msg.url}:{msg.line}:{msg.column}")
            if msg.stack_trace:
                lines.append(f"  Stack: {msg.stack_trace[:200]}")
            return "\n".join(lines)

        if action == "issues":
            issues = cc.get_issues(include_history)
            if not issues:
                return "No issues found"
            lines = ["DevTools Issues:"]
            for iss in issues:
                lines.append(f"  [{iss.severity}] {iss.code}: {iss.message}")
            return "\n".join(lines)

        type_list = types.split(",") if types else None
        messages = cc.get_messages(include_history, type_list, page, size)

        lines = [f"Console ({len(messages)} messages):"]
        for msg in messages:
            prefix = {"error": "ERR", "warning": "WRN", "info": "INF"}.get(msg.type, "LOG")
            text = msg.text[:80] + "..." if len(msg.text) > 80 else msg.text
            lines.append(f"  [{msg.id}] [{prefix}] {text}")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════
    # PERFORMANCE TRACE
    # ═══════════════════════════════════════════════════════════════

    @mcp.tool()
    def perf(
        action: str = "start",
        reload: bool = True,
        auto_stop: float = 5.0,
        save_path: Optional[str] = None
    ) -> str:
        """Performance trace: start/stop/summary. Core Web Vitals."""
        ctx = get_context()
        t = ctx.trace

        if action == "start":
            if t.is_recording:
                return "Already recording. Use perf(action='stop') first."
            t.start(reload=reload, auto_stop_seconds=auto_stop if auto_stop > 0 else None)
            return f"Recording started. Will auto-stop in {auto_stop}s." if auto_stop else "Recording started."

        elif action == "stop":
            if not t.is_recording:
                return "Not recording."
            result = t.stop()
            summary = t.format_summary(result)
            if save_path:
                try:
                    t.save(save_path)
                    summary += f"\n\nTrace saved to: {save_path}"
                except Exception as e:
                    summary += f"\n\nFailed to save: {e}"
            return summary

        elif action == "summary":
            if not t.traces:
                return "No traces recorded. Use perf(action='start') first."
            return t.format_summary()

        return f"Unknown action: {action}"
