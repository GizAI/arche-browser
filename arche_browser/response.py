"""
Structured Response Formatter

Token-efficient response formatting for MCP tools.
Organizes output in structured markdown sections.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ResponseSection:
    """A section in the response."""
    title: str
    content: List[str] = field(default_factory=list)
    level: int = 2  # Markdown heading level


class Response:
    """
    Structured response builder for MCP tools.

    Produces clean, token-efficient markdown output.
    """

    def __init__(self, tool_name: str = ""):
        self.tool_name = tool_name
        self._message: str = ""
        self._sections: List[ResponseSection] = []
        self._snapshot: Optional[str] = None
        self._snapshot_count: int = 0
        self._pages: Optional[List[Dict]] = None
        self._selected_page_idx: int = 0
        self._error: Optional[str] = None
        self._data: Dict[str, Any] = {}

    def set_message(self, message: str) -> "Response":
        """Set the main response message."""
        self._message = message
        return self

    def add_section(self, title: str, content: List[str], level: int = 2) -> "Response":
        """Add a custom section."""
        self._sections.append(ResponseSection(title=title, content=content, level=level))
        return self

    def set_snapshot(self, snapshot: str, node_count: int = 0) -> "Response":
        """Set the page snapshot."""
        self._snapshot = snapshot
        self._snapshot_count = node_count
        return self

    def set_pages(self, pages: List[Dict], selected_idx: int = 0) -> "Response":
        """Set the pages list."""
        self._pages = pages
        self._selected_page_idx = selected_idx
        return self

    def set_error(self, error: str) -> "Response":
        """Set an error message."""
        self._error = error
        return self

    def set_data(self, key: str, value: Any) -> "Response":
        """Set arbitrary data."""
        self._data[key] = value
        return self

    def format(self) -> str:
        """
        Format the response as markdown.

        Returns:
            Formatted markdown string
        """
        lines: List[str] = []

        # Error takes priority
        if self._error:
            lines.append(f"**Error:** {self._error}")
            return "\n".join(lines)

        # Main message
        if self._message:
            lines.append(self._message)

        # Pages section
        if self._pages is not None:
            lines.append("")
            lines.append("## Pages")
            for idx, page in enumerate(self._pages):
                url = page.get("url", "about:blank")
                title = page.get("title", "")
                selected = " [selected]" if idx == self._selected_page_idx else ""

                # Truncate long URLs
                if len(url) > 80:
                    url = url[:77] + "..."

                if title:
                    lines.append(f"{idx}: {title} - {url}{selected}")
                else:
                    lines.append(f"{idx}: {url}{selected}")

        # Custom sections
        for section in self._sections:
            lines.append("")
            heading = "#" * section.level
            lines.append(f"{heading} {section.title}")
            lines.extend(section.content)

        # Snapshot section (last, as it's usually the largest)
        if self._snapshot:
            lines.append("")
            lines.append("## Snapshot")
            if self._snapshot_count:
                lines.append(f"({self._snapshot_count} elements)")
            lines.append("```")
            lines.append(self._snapshot)
            lines.append("```")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """
        Return response as dictionary (for JSON serialization).

        Returns:
            Dict with response components
        """
        result: Dict[str, Any] = {}

        if self._error:
            result["error"] = self._error
            return result

        if self._message:
            result["message"] = self._message

        if self._pages is not None:
            result["pages"] = [
                {
                    "idx": idx,
                    "url": p.get("url", ""),
                    "title": p.get("title", ""),
                    "selected": idx == self._selected_page_idx
                }
                for idx, p in enumerate(self._pages)
            ]

        if self._snapshot:
            result["snapshot"] = self._snapshot
            result["node_count"] = self._snapshot_count

        if self._data:
            result["data"] = self._data

        return result


class ResponseBuilder:
    """
    Factory for creating common response patterns.
    """

    @staticmethod
    def success(message: str, snapshot: Optional[str] = None) -> Response:
        """Create a success response."""
        resp = Response().set_message(message)
        if snapshot:
            resp.set_snapshot(snapshot)
        return resp

    @staticmethod
    def error(message: str) -> Response:
        """Create an error response."""
        return Response().set_error(message)

    @staticmethod
    def with_snapshot(
        message: str,
        snapshot: str,
        node_count: int,
        pages: Optional[List[Dict]] = None,
        selected_idx: int = 0
    ) -> Response:
        """Create a response with snapshot and optional pages."""
        resp = Response().set_message(message).set_snapshot(snapshot, node_count)
        if pages is not None:
            resp.set_pages(pages, selected_idx)
        return resp

    @staticmethod
    def network_requests(
        requests: List[Dict],
        page_idx: int = 0,
        page_size: int = 20
    ) -> Response:
        """Format network requests list."""
        total = len(requests)
        start = page_idx * page_size
        end = min(start + page_size, total)
        page_requests = requests[start:end]

        lines = [f"Showing {start+1}-{end} of {total}"]

        for req in page_requests:
            status = req.get("status", "?")
            method = req.get("method", "GET")
            url = req.get("url", "")
            rtype = req.get("type", "")

            # Truncate URL
            if len(url) > 60:
                url = url[:57] + "..."

            lines.append(f"[{req.get('id', '?')}] {status} {method} {url} ({rtype})")

        resp = Response()
        resp.add_section("Network Requests", lines)

        if end < total:
            resp.set_data("next_page", page_idx + 1)

        return resp

    @staticmethod
    def console_messages(
        messages: List[Dict],
        page_idx: int = 0,
        page_size: int = 30
    ) -> Response:
        """Format console messages list."""
        total = len(messages)
        start = page_idx * page_size
        end = min(start + page_size, total)
        page_messages = messages[start:end]

        lines = [f"Showing {start+1}-{end} of {total}"]

        for msg in page_messages:
            msg_type = msg.get("type", "log")
            text = msg.get("text", "")

            # Truncate long messages
            if len(text) > 100:
                text = text[:97] + "..."

            # Add type prefix
            prefix = {
                "error": "[ERR]",
                "warning": "[WRN]",
                "info": "[INF]",
                "debug": "[DBG]",
            }.get(msg_type, "[LOG]")

            lines.append(f"{prefix} {text}")

        resp = Response()
        resp.add_section("Console", lines)

        if end < total:
            resp.set_data("next_page", page_idx + 1)

        return resp

    @staticmethod
    def history(
        items: List[Any],
        action: str = "search"
    ) -> Response:
        """Format history results."""
        lines = []

        for item in items:
            # Handle both HistoryItem and dict
            if hasattr(item, "url"):
                url = item.url
                title = item.title
                visit_time = item.visit_time
                visit_count = getattr(item, "visit_count", 1)
            else:
                url = item.get("url", "")
                title = item.get("title", "")
                visit_time = item.get("visit_time", "")
                visit_count = item.get("visit_count", 1)

            # Truncate
            if len(url) > 60:
                url = url[:57] + "..."
            if len(title) > 40:
                title = title[:37] + "..."

            # Format time
            if hasattr(visit_time, "strftime"):
                time_str = visit_time.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = str(visit_time)[:16]

            if title:
                lines.append(f"{time_str} ({visit_count}x) {title}")
                lines.append(f"  {url}")
            else:
                lines.append(f"{time_str} ({visit_count}x) {url}")

        resp = Response()
        resp.add_section(f"History ({action})", lines)
        resp.set_data("count", len(items))

        return resp
