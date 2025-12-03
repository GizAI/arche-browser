"""
Arche Browser - MCP Server for Browser Automation and Local PC Control

A complete solution for browser automation via Chrome DevTools Protocol,
plus full local PC control through shell commands and Python execution.
Exposed as an MCP server for use with Claude Code and other AI assistants.

Quick Start:
    # Run MCP server (browser only)
    arche-browser

    # Run with full PC control
    arche-browser --local

    # PC control only (no browser)
    arche-browser --local --no-browser

    # Remote SSE server
    arche-browser --sse --port 8080 --local

    # As Python library
    from arche_browser import Browser, Chrome, LocalControl

    with Chrome() as chrome:
        b = Browser()
        b.goto("https://example.com")
        print(b.title)

    local = LocalControl()
    local.shell("ls -la")
    local.python_exec("print('Hello')")
"""

from .chrome import Chrome, find_chrome
from .browser import Browser, CDP
from .server import create_server, run
from .auth import TokenAuth
from .local import LocalControl

__version__ = "1.2.0"
__all__ = [
    "Chrome",
    "find_chrome",
    "Browser",
    "CDP",
    "create_server",
    "run",
    "TokenAuth",
    "LocalControl",
]
