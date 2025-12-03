"""
CLI entry point for arche-browser.

Usage:
    python -m arche_browser
    arche-browser
    arche-browser --sse --port 8080
    arche-browser --headless
    arche-browser --local  # Full local PC control
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
  arche-browser                         # Browser automation only
  arche-browser --local                 # Browser + full PC control
  arche-browser --local --no-browser    # PC control only (no browser)
  arche-browser --sse --port 8080       # Remote SSE server (with auth)
  arche-browser --sse --local           # Remote with PC control
  arche-browser --headless              # Run Chrome headless

Local MCP config:
  {"command": "arche-browser"}
  {"command": "arche-browser", "args": ["--local"]}

Remote MCP config:
  {"url": "http://HOST:8080/sse?token=YOUR_TOKEN"}

Local Control Tools (--local):
  shell         Execute shell commands (bash/cmd/powershell)
  python_exec   Execute Python code with full system access
  screen_capture  Desktop screenshot
  file_*        File operations (read, write, list, delete, copy, move)
  clipboard_*   Clipboard access
  system_info   System information
  process_*     Process management

With just 'shell' and 'python_exec', AI can control EVERYTHING:
  - Volume, camera, microphone
  - Excel, PowerPoint, any application
  - System maintenance, cleanup, optimization
  - Literally anything a human can do
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

    # Transport
    parser.add_argument(
        "--sse",
        action="store_true",
        help="Run as SSE server for remote access"
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
        help="Run Chrome in headless mode"
    )

    # Authentication
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable authentication (not recommended for remote)"
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Use specific auth token instead of auto-generated"
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
            print("No token found. Run with --sse to generate one.")
        return

    # Validate options
    browser_tools = not args.no_browser
    if args.no_browser and not args.local:
        print("Error: --no-browser requires --local", file=sys.stderr)
        sys.exit(1)

    transport = "sse" if args.sse else "stdio"
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
