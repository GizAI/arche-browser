"""
Performance Trace

Records and analyzes Chrome performance traces
for Core Web Vitals and performance insights.

Design: Builder pattern for trace configuration.
"""

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import time
import tempfile
import os


class TraceCategory(Enum):
    """Chrome trace categories."""
    DEVTOOLS = "devtools.timeline"
    BLINK = "blink.user_timing"
    V8 = "v8.execute"
    LOADING = "loading"
    RENDERING = "disabled-by-default-devtools.timeline"
    SCREENSHOT = "disabled-by-default-devtools.screenshot"
    STACK = "disabled-by-default-devtools.timeline.stack"
    CPU = "disabled-by-default-v8.cpu_profiler"


@dataclass
class WebVitals:
    """Core Web Vitals metrics."""
    lcp: Optional[float] = None  # Largest Contentful Paint (ms)
    fcp: Optional[float] = None  # First Contentful Paint (ms)
    cls: Optional[float] = None  # Cumulative Layout Shift
    fid: Optional[float] = None  # First Input Delay (ms)
    ttfb: Optional[float] = None  # Time to First Byte (ms)
    tti: Optional[float] = None  # Time to Interactive (ms)


@dataclass
class TraceEvent:
    """Single trace event."""
    name: str
    cat: str
    ph: str  # Phase: B=begin, E=end, X=complete, I=instant
    ts: int  # Timestamp (microseconds)
    dur: Optional[int] = None  # Duration (microseconds)
    pid: int = 0
    tid: int = 0
    args: Dict = field(default_factory=dict)


@dataclass
class CallFrame:
    """CPU profiler call frame."""
    function_name: str
    url: str
    line: int
    column: int
    self_time: float  # ms
    total_time: float  # ms
    children: List["CallFrame"] = field(default_factory=list)


@dataclass
class TraceResult:
    """Trace recording result."""
    web_vitals: WebVitals
    events: List[TraceEvent]
    duration: float  # seconds
    # Performance insights
    long_tasks: List[Dict] = field(default_factory=list)  # Tasks > 50ms
    layout_shifts: List[Dict] = field(default_factory=list)
    network_requests: List[Dict] = field(default_factory=list)
    # Raw data
    raw_json: Optional[str] = None


class PerformanceTrace:
    """
    Performance trace recorder and analyzer.

    Usage:
        trace = PerformanceTrace(browser)
        trace.start(reload=True)
        # ... interact with page ...
        result = trace.stop()
        print(result.web_vitals)
    """

    # Default trace categories (from Chrome DevTools)
    DEFAULT_CATEGORIES = [
        "-*",  # Disable all first
        "blink.console",
        "blink.user_timing",
        "devtools.timeline",
        "disabled-by-default-devtools.screenshot",
        "disabled-by-default-devtools.timeline",
        "disabled-by-default-devtools.timeline.frame",
        "disabled-by-default-devtools.timeline.stack",
        "disabled-by-default-v8.cpu_profiler",
        "latencyInfo",
        "loading",
        "v8.execute",
        "v8",
    ]

    def __init__(self, browser: Any):
        self.browser = browser
        self._recording = False
        self._start_time = 0.0
        self._start_url = ""
        self._traces: List[TraceResult] = []

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(
        self,
        reload: bool = False,
        categories: Optional[List[str]] = None,
        auto_stop_seconds: Optional[float] = None
    ) -> bool:
        """
        Start performance trace recording.

        Args:
            reload: Navigate to about:blank first, then reload
            categories: Custom trace categories (uses defaults if None)
            auto_stop_seconds: Auto-stop after N seconds

        Returns:
            True if started successfully
        """
        if self._recording:
            return False

        cdp = self.browser.cdp
        self._start_url = self.browser.url
        self._start_time = time.time()

        # Clear and reload if requested
        if reload:
            cdp.send("Page.navigate", {"url": "about:blank"})
            time.sleep(0.5)

        # Start tracing
        cats = categories or self.DEFAULT_CATEGORIES
        cdp.send("Tracing.start", {
            "traceConfig": {
                "recordMode": "recordAsMuchAsPossible",
                "includedCategories": cats,
            },
            "transferMode": "ReturnAsStream",
        })

        self._recording = True

        # Reload original page if requested
        if reload:
            cdp.send("Page.navigate", {"url": self._start_url})
            # Wait for load
            try:
                self.browser.wait_load(timeout=10)
            except Exception:
                pass

        # Auto-stop
        if auto_stop_seconds:
            import threading
            def delayed_stop():
                time.sleep(auto_stop_seconds)
                if self._recording:
                    self.stop()
            threading.Thread(target=delayed_stop, daemon=True).start()

        return True

    def stop(self) -> TraceResult:
        """
        Stop recording and analyze trace.

        Returns:
            TraceResult with web vitals and insights
        """
        if not self._recording:
            raise RuntimeError("Not recording")

        cdp = self.browser.cdp
        duration = time.time() - self._start_time

        # End tracing and collect data
        cdp.send("Tracing.end")

        # Collect trace events
        events_json = []
        stream_handle = None

        # Wait for trace complete
        trace_complete = False
        collected_events = []

        def on_complete(params):
            nonlocal trace_complete, stream_handle
            stream_handle = params.get("stream")
            trace_complete = True

        def on_data(params):
            value = params.get("value", "")
            if value:
                collected_events.append(value)

        cdp.on("Tracing.tracingComplete", on_complete)
        cdp.on("Tracing.dataCollected", on_data)

        # Poll until complete
        timeout = time.time() + 30
        while not trace_complete and time.time() < timeout:
            cdp.poll(0.1)

        self._recording = False

        # Read from stream if available
        if stream_handle:
            try:
                while True:
                    chunk = cdp.send("IO.read", {"handle": stream_handle})
                    if chunk.get("data"):
                        collected_events.append(chunk["data"])
                    if chunk.get("eof"):
                        break
                cdp.send("IO.close", {"handle": stream_handle})
            except Exception:
                pass

        # Parse events
        raw_json = "".join(collected_events)
        events = self._parse_events(raw_json)

        # Analyze
        web_vitals = self._extract_web_vitals(events)
        long_tasks = self._find_long_tasks(events)
        layout_shifts = self._find_layout_shifts(events)
        network = self._extract_network(events)

        result = TraceResult(
            web_vitals=web_vitals,
            events=events,
            duration=duration,
            long_tasks=long_tasks,
            layout_shifts=layout_shifts,
            network_requests=network,
            raw_json=raw_json if len(raw_json) < 1_000_000 else None,
        )

        self._traces.append(result)
        return result

    def _parse_events(self, raw: str) -> List[TraceEvent]:
        """Parse raw trace JSON into events."""
        events = []
        try:
            data = json.loads(raw) if raw else {}
            trace_events = data.get("traceEvents", data if isinstance(data, list) else [])

            for e in trace_events[:10000]:  # Limit for memory
                events.append(TraceEvent(
                    name=e.get("name", ""),
                    cat=e.get("cat", ""),
                    ph=e.get("ph", ""),
                    ts=e.get("ts", 0),
                    dur=e.get("dur"),
                    pid=e.get("pid", 0),
                    tid=e.get("tid", 0),
                    args=e.get("args", {}),
                ))
        except json.JSONDecodeError:
            pass
        return events

    def _extract_web_vitals(self, events: List[TraceEvent]) -> WebVitals:
        """Extract Core Web Vitals from trace events."""
        vitals = WebVitals()

        for e in events:
            name = e.name

            # First Contentful Paint
            if name == "firstContentfulPaint" or name == "firstPaint":
                if vitals.fcp is None or e.ts < vitals.fcp:
                    vitals.fcp = e.ts / 1000  # Convert to ms

            # Largest Contentful Paint
            if name == "largestContentfulPaint::Candidate":
                lcp_time = e.args.get("data", {}).get("candidateIndex", e.ts / 1000)
                if vitals.lcp is None or lcp_time > vitals.lcp:
                    vitals.lcp = e.ts / 1000

            # Layout Shift
            if name == "LayoutShift":
                score = e.args.get("data", {}).get("score", 0)
                if not e.args.get("data", {}).get("had_recent_input", False):
                    vitals.cls = (vitals.cls or 0) + score

            # First Input Delay (from responsiveness)
            if "EventTiming" in name or name == "firstInput":
                fid = e.args.get("data", {}).get("processingStart", 0) - e.ts
                if fid > 0 and (vitals.fid is None or fid < vitals.fid):
                    vitals.fid = fid / 1000

            # Time to First Byte
            if name == "ResourceReceiveResponse":
                url = e.args.get("data", {}).get("url", "")
                if url and (vitals.ttfb is None):
                    vitals.ttfb = e.ts / 1000

        return vitals

    def _find_long_tasks(self, events: List[TraceEvent]) -> List[Dict]:
        """Find tasks longer than 50ms."""
        long_tasks = []
        for e in events:
            if e.name == "RunTask" and e.dur and e.dur > 50000:  # > 50ms
                long_tasks.append({
                    "duration_ms": e.dur / 1000,
                    "timestamp_ms": e.ts / 1000,
                    "category": e.cat,
                })
        return sorted(long_tasks, key=lambda x: -x["duration_ms"])[:20]

    def _find_layout_shifts(self, events: List[TraceEvent]) -> List[Dict]:
        """Find layout shift events."""
        shifts = []
        for e in events:
            if e.name == "LayoutShift":
                data = e.args.get("data", {})
                if not data.get("had_recent_input", False):
                    shifts.append({
                        "score": data.get("score", 0),
                        "timestamp_ms": e.ts / 1000,
                    })
        return shifts

    def _extract_network(self, events: List[TraceEvent]) -> List[Dict]:
        """Extract network request events."""
        requests = {}
        for e in events:
            if e.name == "ResourceSendRequest":
                req_id = e.args.get("data", {}).get("requestId", "")
                if req_id:
                    requests[req_id] = {
                        "url": e.args.get("data", {}).get("url", ""),
                        "start_ms": e.ts / 1000,
                    }
            elif e.name == "ResourceReceiveResponse":
                req_id = e.args.get("data", {}).get("requestId", "")
                if req_id in requests:
                    requests[req_id]["status"] = e.args.get("data", {}).get("statusCode")
            elif e.name == "ResourceFinish":
                req_id = e.args.get("data", {}).get("requestId", "")
                if req_id in requests:
                    requests[req_id]["end_ms"] = e.ts / 1000
                    requests[req_id]["duration_ms"] = (
                        requests[req_id]["end_ms"] - requests[req_id]["start_ms"]
                    )

        return list(requests.values())

    def save(self, path: str) -> str:
        """Save last trace to file."""
        if not self._traces:
            raise RuntimeError("No traces recorded")

        result = self._traces[-1]
        if result.raw_json:
            with open(path, "w") as f:
                f.write(result.raw_json)
            return path

        raise RuntimeError("Trace data not available for saving")

    def format_summary(self, result: Optional[TraceResult] = None) -> str:
        """Format trace result as readable summary."""
        result = result or (self._traces[-1] if self._traces else None)
        if not result:
            return "No trace data"

        lines = ["## Performance Trace Summary", ""]

        # Web Vitals
        lines.append("### Core Web Vitals")
        v = result.web_vitals
        if v.lcp:
            status = "🟢" if v.lcp < 2500 else "🟡" if v.lcp < 4000 else "🔴"
            lines.append(f"  LCP: {v.lcp:.0f}ms {status}")
        if v.fcp:
            status = "🟢" if v.fcp < 1800 else "🟡" if v.fcp < 3000 else "🔴"
            lines.append(f"  FCP: {v.fcp:.0f}ms {status}")
        if v.cls is not None:
            status = "🟢" if v.cls < 0.1 else "🟡" if v.cls < 0.25 else "🔴"
            lines.append(f"  CLS: {v.cls:.3f} {status}")
        if v.fid:
            status = "🟢" if v.fid < 100 else "🟡" if v.fid < 300 else "🔴"
            lines.append(f"  FID: {v.fid:.0f}ms {status}")
        if v.ttfb:
            status = "🟢" if v.ttfb < 800 else "🟡" if v.ttfb < 1800 else "🔴"
            lines.append(f"  TTFB: {v.ttfb:.0f}ms {status}")

        # Long tasks
        if result.long_tasks:
            lines.append("")
            lines.append("### Long Tasks (>50ms)")
            for task in result.long_tasks[:5]:
                lines.append(f"  {task['duration_ms']:.0f}ms @ {task['timestamp_ms']:.0f}ms")

        # Layout shifts
        if result.layout_shifts:
            lines.append("")
            lines.append("### Layout Shifts")
            total_cls = sum(s["score"] for s in result.layout_shifts)
            lines.append(f"  Total CLS: {total_cls:.3f} ({len(result.layout_shifts)} shifts)")

        # Network
        if result.network_requests:
            lines.append("")
            lines.append(f"### Network ({len(result.network_requests)} requests)")
            slow = [r for r in result.network_requests if r.get("duration_ms", 0) > 500]
            if slow:
                lines.append("  Slow requests (>500ms):")
                for r in sorted(slow, key=lambda x: -x.get("duration_ms", 0))[:5]:
                    url = r["url"][:50] + "..." if len(r.get("url", "")) > 50 else r.get("url", "")
                    lines.append(f"    {r.get('duration_ms', 0):.0f}ms {url}")

        lines.append("")
        lines.append(f"Total recording: {result.duration:.1f}s")

        return "\n".join(lines)

    @property
    def traces(self) -> List[TraceResult]:
        """All recorded traces."""
        return self._traces
