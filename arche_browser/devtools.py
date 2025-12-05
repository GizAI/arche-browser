"""
DevTools Integration

Detects and integrates with Chrome DevTools windows.
Reads selected elements and network requests from DevTools UI.

Design: Facade pattern for DevTools access.
"""

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import re


@dataclass
class DevToolsState:
    """Current DevTools UI state."""
    # Element selected in Elements panel
    selected_backend_node_id: Optional[int] = None
    selected_uid: Optional[str] = None
    # Network request selected in Network panel
    selected_request_id: Optional[str] = None
    selected_request_idx: Optional[int] = None
    # Active panel
    active_panel: str = ""


class DevToolsIntegration:
    """
    Integrates with open DevTools windows.

    Detects DevTools pages and extracts UI state.
    """

    def __init__(self, browser: Any):
        self.browser = browser
        self._page_to_devtools: Dict[str, str] = {}  # page_id -> devtools_page_id
        self._enabled = False

    def detect(self) -> Dict[str, str]:
        """
        Detect open DevTools windows and map to pages.

        Returns:
            Dict mapping page IDs to their DevTools page IDs
        """
        import requests

        self._page_to_devtools.clear()

        try:
            pages = requests.get(
                f"http://{self.browser.cdp.address}/json/list",
                timeout=5
            ).json()
        except Exception:
            return {}

        # Find DevTools pages
        devtools_pages = [p for p in pages if p.get("url", "").startswith("devtools://")]

        for dt_page in devtools_pages:
            title = dt_page.get("title", "")
            url_match = self._extract_url_from_title(title)

            if url_match:
                # Find corresponding content page
                for page in pages:
                    if not page.get("url", "").startswith("devtools://"):
                        page_url = page.get("url", "")
                        if self._urls_match(page_url, url_match):
                            self._page_to_devtools[page["id"]] = dt_page["id"]
                            break

        return self._page_to_devtools

    def _extract_url_from_title(self, title: str) -> Optional[str]:
        """Extract URL from DevTools window title."""
        # DevTools title format: "DevTools - domain.com/path"
        match = re.search(r"DevTools\s*[-–]\s*(.+)", title)
        if match:
            url_like = match.group(1).strip()
            # Could be just domain or full URL
            if not url_like.startswith(("http://", "https://")):
                return f"https://{url_like}"
            return url_like
        return None

    def _urls_match(self, url1: str, url2: str) -> bool:
        """Check if URLs match (ignoring protocol and trailing slash)."""
        def normalize(u: str) -> str:
            u = re.sub(r"^https?://", "", u)
            u = u.rstrip("/")
            return u.lower()

        return normalize(url1) == normalize(url2) or url2 in url1

    def get_state(self, page_id: Optional[str] = None) -> DevToolsState:
        """
        Get DevTools UI state for a page.

        Args:
            page_id: Target page ID. If None, uses current page.

        Returns:
            DevToolsState with selected element/request info
        """
        state = DevToolsState()

        if page_id is None:
            # Get current page ID
            try:
                current = self.browser.pages()[0]
                page_id = current.get("id")
            except Exception:
                return state

        if not page_id:
            return state

        # Ensure detection is done
        if not self._page_to_devtools:
            self.detect()

        devtools_id = self._page_to_devtools.get(page_id)
        if not devtools_id:
            return state

        # Connect to DevTools page and query state
        try:
            state = self._query_devtools_state(devtools_id)
        except Exception:
            pass

        return state

    def _query_devtools_state(self, devtools_page_id: str) -> DevToolsState:
        """Query DevTools page for current UI state."""
        state = DevToolsState()

        # Create temporary connection to DevTools page
        import websocket

        try:
            # Get WebSocket URL for DevTools page
            import requests
            pages = requests.get(
                f"http://{self.browser.cdp.address}/json/list",
                timeout=5
            ).json()

            dt_page = next((p for p in pages if p.get("id") == devtools_page_id), None)
            if not dt_page:
                return state

            ws_url = dt_page.get("webSocketDebuggerUrl")
            if not ws_url:
                return state

            ws = websocket.create_connection(ws_url, timeout=5)

            try:
                # Query DevTools UI state via Runtime.evaluate
                query = {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": """
                        (async () => {
                            try {
                                const UI = await import('/bundled/ui/legacy/legacy.js');
                                const SDK = await import('/bundled/core/sdk/sdk.js');

                                const ctx = UI.Context.Context.instance();
                                const node = ctx.flavor(SDK.DOMModel.DOMNode);
                                const request = ctx.flavor(SDK.NetworkRequest.NetworkRequest);

                                return {
                                    nodeId: node?.backendNodeId(),
                                    requestId: request?.requestId(),
                                };
                            } catch (e) {
                                return { error: e.message };
                            }
                        })()
                        """,
                        "awaitPromise": True,
                        "returnByValue": True,
                    }
                }

                import json
                ws.send(json.dumps(query))

                # Wait for response
                response = json.loads(ws.recv())
                result = response.get("result", {}).get("result", {}).get("value", {})

                if result.get("nodeId"):
                    state.selected_backend_node_id = result["nodeId"]

                if result.get("requestId"):
                    state.selected_request_id = result["requestId"]

            finally:
                ws.close()

        except Exception:
            pass

        return state

    def resolve_uid(self, state: DevToolsState, snapshot: Any) -> Optional[str]:
        """
        Resolve selected element to snapshot UID.

        Args:
            state: DevTools state with backend node ID
            snapshot: Current Snapshot instance

        Returns:
            UID if element found in snapshot, None otherwise
        """
        if not state.selected_backend_node_id or not snapshot:
            return None

        # Search snapshot for matching backend node ID
        backend_map = getattr(snapshot, "_backend_map", {})
        return backend_map.get(state.selected_backend_node_id)


class DevToolsContext:
    """
    High-level DevTools context manager.

    Combines all DevTools functionality.
    """

    def __init__(self, browser: Any):
        self.browser = browser
        self.integration = DevToolsIntegration(browser)
        self._snapshot_manager = None

    def set_snapshot_manager(self, manager: Any):
        """Set snapshot manager for UID resolution."""
        self._snapshot_manager = manager

    def get_selected_element_uid(self) -> Optional[str]:
        """Get UID of element selected in DevTools Elements panel."""
        state = self.integration.get_state()
        if state.selected_backend_node_id and self._snapshot_manager:
            snapshot = self._snapshot_manager.current
            if snapshot:
                return self.integration.resolve_uid(state, snapshot)
        return None

    def get_selected_request_id(self) -> Optional[str]:
        """Get ID of request selected in DevTools Network panel."""
        state = self.integration.get_state()
        return state.selected_request_id

    def attach_to_response(self, response: Dict) -> Dict:
        """
        Attach DevTools selection info to response.

        Args:
            response: Response dict to augment

        Returns:
            Augmented response with DevTools info
        """
        state = self.integration.get_state()

        if state.selected_backend_node_id:
            response["devtools_selected_element"] = state.selected_backend_node_id

            # Try to resolve to UID
            uid = self.get_selected_element_uid()
            if uid:
                response["devtools_selected_uid"] = uid

        if state.selected_request_id:
            response["devtools_selected_request"] = state.selected_request_id

        return response
