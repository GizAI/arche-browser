"""
CLI entry point for arche-browser.

Usage:
    arche-browser                    # SSE server on port 8080 (default)
    arche-browser --local            # With full PC control
    arche-browser --stdio            # For MCP clients (Claude Code)
    arche-browser --headless         # Hide browser window
"""

import argparse
import sys

from .server import run
from .auth import TokenAuth


def main():
    parser = argparse.ArgumentParser(
        prog="arche-browser",
        description="MCP Server for Browser Automation and Local PC Control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  arche-browser                       # Start SSE server (default)
  arche-browser --local               # With full PC control
  arche-browser --port 9000           # Custom port
  arche-browser --headless            # Hide browser window
  arche-browser --no-auth             # Disable token auth (dev only)
  arche-browser --stdio               # For MCP clients (Claude Code)

For Claude Code (~/.claude/settings.json):
  {"mcpServers": {"arche": {"command": "arche-browser", "args": ["--stdio"]}}}
  {"mcpServers": {"arche": {"command": "arche-browser", "args": ["--stdio", "--local"]}}}

For remote access:
  {"mcpServers": {"arche": {"url": "http://HOST:8080/sse?token=YOUR_TOKEN"}}}

Local Control Tools (--local):
  shell         Execute shell commands (bash/cmd/powershell)
  python_exec   Execute Python code with full system access
  screen_capture  Desktop screenshot
  file_*        File operations (read, write, list, delete, copy, move)
  clipboard_*   Clipboard access
  system_info   System information
  process_*     Process management
        """
    )

    # Mode selection
    parser.add_argument(
        "--local",
        action="store_true",
        help="Enable full local PC control (shell, python, files, etc.)"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Disable browser tools (use with --local for PC-only control)"
    )

    # Transport - stdio is opt-in now, SSE is default
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Use stdio transport (for MCP clients like Claude Code)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="SSE server port (default: 8080)"
    )

    # Browser options
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome in headless mode (no visible window)"
    )

    # Authentication
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable token authentication (not recommended)"
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Use specific auth token"
    )
    parser.add_argument(
        "--reset-token",
        action="store_true",
        help="Generate new auth token and exit"
    )
    parser.add_argument(
        "--show-token",
        action="store_true",
        help="Show current auth token and exit"
    )

    args = parser.parse_args()

    # Token management commands
    if args.reset_token:
        token = TokenAuth.reset()
        print(f"New token: {token}")
        print(f"Saved to: {TokenAuth.TOKEN_FILE}")
        return

    if args.show_token:
        token = TokenAuth.load()
        if token:
            print(f"Token: {token}")
            print(f"File: {TokenAuth.TOKEN_FILE}")
        else:
            print("No token found. Run arche-browser to generate one.")
        return

    # Validate options
    browser_tools = not args.no_browser
    if args.no_browser and not args.local:
        print("Error: --no-browser requires --local", file=sys.stderr)
        sys.exit(1)

    # SSE is default, stdio is opt-in
    transport = "stdio" if args.stdio else "sse"

    run(
        transport=transport,
        port=args.port,
        headless=args.headless,
        auth=not args.no_auth,
        token=args.token,
        local_control=args.local,
        browser_tools=browser_tools
    )


if __name__ == "__main__":
    main()
