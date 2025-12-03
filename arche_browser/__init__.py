"""
Arche Browser - MCP Server for Browser Automation

A complete solution for browser automation via Chrome DevTools Protocol,
exposed as an MCP server for use with Claude Code and other AI assistants.

Quick Start:
    # Run MCP server
    arche-browser

    # Or use as library
    from arche_browser import Browser, Chrome

    with Chrome() as chrome:
        b = Browser()
        b.goto("https://example.com")
        print(b.title)
"""

from .chrome import Chrome, find_chrome
from .browser import Browser, CDP
from .server import create_server, run
from .auth import TokenAuth

__version__ = "1.0.0"
__all__ = [
    "Chrome",
    "find_chrome",
    "Browser",
    "CDP",
    "create_server",
    "run",
    "TokenAuth",
]
