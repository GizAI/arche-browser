"""
Browser Context

Unified context object that manages all browser-related state.
Replaces scattered global variables with a single cohesive object.

Design: Facade pattern for browser subsystems.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import threading


@dataclass
class BrowserContext:
    """
    Unified browser context managing all subsystems.

    Provides lazy initialization and thread-safe access.
    """
    browser: Any = None
    _snapshot_mgr: Any = field(default=None, repr=False)
    _network_collector: Any = field(default=None, repr=False)
    _console_collector: Any = field(default=None, repr=False)
    _trace: Any = field(default=None, repr=False)
    _devtools: Any = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def snapshot_mgr(self):
        """Lazy-init SnapshotManager."""
        if self._snapshot_mgr is None:
            with self._lock:
                if self._snapshot_mgr is None:
                    from .snapshot import SnapshotManager
                    self._snapshot_mgr = SnapshotManager(self.browser)
        return self._snapshot_mgr

    @property
    def network(self):
        """Lazy-init NetworkCollector."""
        if self._network_collector is None:
            with self._lock:
                if self._network_collector is None:
                    from .collector import NetworkCollector
                    self._network_collector = NetworkCollector(self.browser)
                    self._network_collector.enable()
        return self._network_collector

    @property
    def console(self):
        """Lazy-init ConsoleCollector."""
        if self._console_collector is None:
            with self._lock:
                if self._console_collector is None:
                    from .collector import ConsoleCollector
                    self._console_collector = ConsoleCollector(self.browser)
                    self._console_collector.enable()
        return self._console_collector

    @property
    def trace(self):
        """Lazy-init PerformanceTrace."""
        if self._trace is None:
            with self._lock:
                if self._trace is None:
                    from .trace import PerformanceTrace
                    self._trace = PerformanceTrace(self.browser)
        return self._trace

    @property
    def devtools(self):
        """Lazy-init DevToolsContext."""
        if self._devtools is None:
            with self._lock:
                if self._devtools is None:
                    from .devtools import DevToolsContext
                    self._devtools = DevToolsContext(self.browser)
                    self._devtools.set_snapshot_manager(self.snapshot_mgr)
        return self._devtools

    def reset(self):
        """Reset all subsystems (call when browser reconnects)."""
        with self._lock:
            self._snapshot_mgr = None
            self._network_collector = None
            self._console_collector = None
            self._trace = None
            self._devtools = None
