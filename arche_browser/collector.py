"""
Network & Console Collectors

Collects and manages network requests and console messages
across page navigations.

Design: Template Method pattern for common collector behavior.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
import time
import threading


T = TypeVar('T')


class ResourceType(Enum):
    """Network resource types."""
    DOCUMENT = "Document"
    STYLESHEET = "Stylesheet"
    IMAGE = "Image"
    MEDIA = "Media"
    FONT = "Font"
    SCRIPT = "Script"
    XHR = "XHR"
    FETCH = "Fetch"
    WEBSOCKET = "WebSocket"
    OTHER = "Other"


class MessageType(Enum):
    """Console message types."""
    LOG = "log"
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class NetworkRequest:
    """Captured network request."""
    id: int
    url: str
    method: str
    resource_type: str
    request_headers: Dict[str, str] = field(default_factory=dict)
    post_data: Optional[str] = None
    status: Optional[int] = None
    status_text: str = ""
    response_headers: Dict[str, str] = field(default_factory=dict)
    mime_type: str = ""
    timestamp: float = 0.0
    response_time: Optional[float] = None
    error: Optional[str] = None
    request_id: str = ""


@dataclass
class ConsoleMessage:
    """Captured console message."""
    id: int
    type: str
    text: str
    url: str = ""
    line: int = 0
    column: int = 0
    timestamp: float = 0.0
    stack_trace: str = ""


@dataclass
class Issue:
    """DevTools issue (from Audits API)."""
    id: int
    code: str
    severity: str
    message: str
    details: Dict = field(default_factory=dict)
    timestamp: float = 0.0


class Collector(Generic[T]):
    """
    Generic collector with navigation-based history.

    Keeps data from last N navigations.
    """

    def __init__(self, max_navigations: int = 3):
        self._max_nav = max_navigations
        self._history: deque = deque(maxlen=max_navigations)
        self._current: List[T] = []
        self._id_counter = 0
        self._id_map: Dict[int, T] = {}
        self._lock = threading.Lock()

    def on_navigate(self):
        """Called on page navigation. Archives current data."""
        with self._lock:
            if self._current:
                self._history.append(list(self._current))
            self._current = []

    def add(self, item: T) -> int:
        """Add item, return assigned ID."""
        with self._lock:
            self._id_counter += 1
            self._id_map[self._id_counter] = item
            self._current.append(item)
            return self._id_counter

    def get(self, include_history: bool = False) -> List[T]:
        """Get items, optionally including history."""
        with self._lock:
            if include_history:
                all_items = []
                for h in self._history:
                    all_items.extend(h)
                all_items.extend(self._current)
                return all_items
            return list(self._current)

    def get_by_id(self, item_id: int) -> Optional[T]:
        """Get item by ID."""
        return self._id_map.get(item_id)

    def clear(self):
        """Clear all data."""
        with self._lock:
            self._history.clear()
            self._current = []
            self._id_map.clear()

    def __len__(self) -> int:
        return len(self._current)


class AbstractCDPCollector(ABC):
    """
    Abstract base for CDP event collectors.

    Template Method pattern: subclasses implement _subscribe_events().
    """

    def __init__(self, browser: Any):
        self.browser = browser
        self._enabled = False

    @abstractmethod
    def _subscribe_events(self):
        """Subscribe to CDP events. Implemented by subclasses."""
        pass

    @abstractmethod
    def _enable_domains(self):
        """Enable required CDP domains. Implemented by subclasses."""
        pass

    @abstractmethod
    def _disable_domains(self):
        """Disable CDP domains. Implemented by subclasses."""
        pass

    def _on_main_frame_navigate(self):
        """Override in subclass to handle main frame navigation."""
        pass

    def _on_navigate(self, params: Dict):
        """Common navigation handler."""
        if params.get("frame", {}).get("parentId") is None:
            self._on_main_frame_navigate()

    def enable(self):
        """Enable collection."""
        if self._enabled:
            return
        self.browser.cdp.on("Page.frameNavigated", self._on_navigate)
        self._subscribe_events()
        self._enable_domains()
        self._enabled = True

    def disable(self):
        """Disable collection."""
        if not self._enabled:
            return
        try:
            self._disable_domains()
        except Exception:
            pass
        self._enabled = False


class NetworkCollector(AbstractCDPCollector):
    """
    Collects network requests via CDP.

    Subscribes to Network domain events.
    """

    def __init__(self, browser: Any):
        super().__init__(browser)
        self._collector: Collector[NetworkRequest] = Collector()
        self._pending: Dict[str, NetworkRequest] = {}

    def _subscribe_events(self):
        cdp = self.browser.cdp
        cdp.on("Network.requestWillBeSent", self._on_request)
        cdp.on("Network.responseReceived", self._on_response)
        cdp.on("Network.loadingFailed", self._on_failed)

    def _enable_domains(self):
        self.browser.cdp.send("Network.enable")

    def _disable_domains(self):
        self.browser.cdp.send("Network.disable")

    def _on_main_frame_navigate(self):
        self._collector.on_navigate()

    def _on_request(self, params: Dict):
        """Handle request sent."""
        req = params.get("request", {})
        request_id = params.get("requestId", "")

        nr = NetworkRequest(
            id=0,
            url=req.get("url", ""),
            method=req.get("method", "GET"),
            resource_type=params.get("type", "Other"),
            request_headers=req.get("headers", {}),
            post_data=req.get("postData"),
            timestamp=params.get("timestamp", time.time()),
            request_id=request_id,
        )
        self._pending[request_id] = nr

    def _on_response(self, params: Dict):
        """Handle response received."""
        request_id = params.get("requestId", "")
        nr = self._pending.pop(request_id, None)
        if not nr:
            return

        resp = params.get("response", {})
        nr.status = resp.get("status")
        nr.status_text = resp.get("statusText", "")
        nr.response_headers = resp.get("headers", {})
        nr.mime_type = resp.get("mimeType", "")
        nr.response_time = params.get("timestamp", time.time())
        nr.id = self._collector.add(nr)

    def _on_failed(self, params: Dict):
        """Handle loading failed."""
        request_id = params.get("requestId", "")
        nr = self._pending.pop(request_id, None)
        if not nr:
            return

        nr.error = params.get("errorText", "Failed")
        nr.status = 0
        nr.id = self._collector.add(nr)

    def get(
        self,
        include_history: bool = False,
        resource_types: Optional[List[str]] = None,
        page_idx: int = 0,
        page_size: int = 50
    ) -> List[NetworkRequest]:
        """Get requests with optional filtering and pagination."""
        items = self._collector.get(include_history)

        if resource_types:
            items = [r for r in items if r.resource_type.lower() in [t.lower() for t in resource_types]]

        start = page_idx * page_size
        return items[start:start + page_size]

    def get_by_id(self, req_id: int) -> Optional[NetworkRequest]:
        """Get request by ID."""
        return self._collector.get_by_id(req_id)

    def clear(self):
        """Clear all data."""
        self._collector.clear()
        self._pending.clear()


class ConsoleCollector(AbstractCDPCollector):
    """
    Collects console messages and errors.

    Subscribes to Runtime and Log domain events.
    """

    def __init__(self, browser: Any):
        super().__init__(browser)
        self._messages: Collector[ConsoleMessage] = Collector()
        self._issues: Collector[Issue] = Collector()

    def _subscribe_events(self):
        cdp = self.browser.cdp
        cdp.on("Runtime.consoleAPICalled", self._on_console)
        cdp.on("Runtime.exceptionThrown", self._on_exception)
        cdp.on("Log.entryAdded", self._on_log)
        cdp.on("Audits.issueAdded", self._on_issue)

    def _enable_domains(self):
        cdp = self.browser.cdp
        cdp.send("Runtime.enable")
        cdp.send("Log.enable")
        try:
            cdp.send("Audits.enable")
        except Exception:
            pass

    def _disable_domains(self):
        cdp = self.browser.cdp
        cdp.send("Runtime.disable")
        cdp.send("Log.disable")

    def _on_main_frame_navigate(self):
        self._messages.on_navigate()
        self._issues.on_navigate()

    def _on_console(self, params: Dict):
        """Handle console API call."""
        args = params.get("args", [])
        text_parts = []
        for arg in args:
            if "value" in arg:
                text_parts.append(str(arg["value"]))
            elif "description" in arg:
                text_parts.append(arg["description"])

        stack = params.get("stackTrace", {})
        call_frames = stack.get("callFrames", [])
        frame = call_frames[0] if call_frames else {}

        msg = ConsoleMessage(
            id=0,
            type=params.get("type", "log"),
            text=" ".join(text_parts),
            url=frame.get("url", ""),
            line=frame.get("lineNumber", 0),
            column=frame.get("columnNumber", 0),
            timestamp=params.get("timestamp", time.time()),
        )
        msg.id = self._messages.add(msg)

    def _on_exception(self, params: Dict):
        """Handle uncaught exception."""
        ex = params.get("exceptionDetails", {})
        exception = ex.get("exception", {})

        msg = ConsoleMessage(
            id=0,
            type="error",
            text=exception.get("description", ex.get("text", "Error")),
            url=ex.get("url", ""),
            line=ex.get("lineNumber", 0),
            column=ex.get("columnNumber", 0),
            timestamp=params.get("timestamp", time.time()),
            stack_trace=ex.get("stackTrace", {}).get("description", ""),
        )
        msg.id = self._messages.add(msg)

    def _on_log(self, params: Dict):
        """Handle log entry."""
        entry = params.get("entry", {})
        msg = ConsoleMessage(
            id=0,
            type=entry.get("level", "log"),
            text=entry.get("text", ""),
            url=entry.get("url", ""),
            line=entry.get("lineNumber", 0),
            timestamp=entry.get("timestamp", time.time()) / 1000,
        )
        msg.id = self._messages.add(msg)

    def _on_issue(self, params: Dict):
        """Handle DevTools issue."""
        issue = params.get("issue", {})
        code = issue.get("code", "unknown")

        details = issue.get("details", {})
        message = ""
        for key in details:
            if isinstance(details[key], dict) and "reason" in details[key]:
                message = details[key]["reason"]
                break

        iss = Issue(
            id=0,
            code=code,
            severity=issue.get("severity", "warning"),
            message=message or code,
            details=details,
            timestamp=time.time(),
        )
        iss.id = self._issues.add(iss)

    def get_messages(
        self,
        include_history: bool = False,
        types: Optional[List[str]] = None,
        page_idx: int = 0,
        page_size: int = 50
    ) -> List[ConsoleMessage]:
        """Get messages with filtering and pagination."""
        items = self._messages.get(include_history)

        if types:
            items = [m for m in items if m.type in types]

        start = page_idx * page_size
        return items[start:start + page_size]

    def get_issues(self, include_history: bool = False) -> List[Issue]:
        """Get DevTools issues."""
        return self._issues.get(include_history)

    def get_by_id(self, msg_id: int) -> Optional[ConsoleMessage]:
        """Get message by ID."""
        return self._messages.get_by_id(msg_id)

    def clear(self):
        """Clear all data."""
        self._messages.clear()
        self._issues.clear()
