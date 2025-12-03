"""
CLI entry point for arche-browser.

Usage:
    python -m arche_browser
    arche-browser
    arche-browser --sse --port 8080
    arche-browser --headless
"""

import argparse
import sys

from .server import run
from .auth import TokenAuth


def main():
    parser = argparse.ArgumentParser(
        prog="arche-browser",
        description="MCP Server for Browser Automation via Chrome DevTools Protocol",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  arche-browser                      # Run as stdio MCP server
  arche-browser --sse --port 8080    # Run as SSE server (with auth)
  arche-browser --sse --no-auth      # Run SSE without auth (not recommended)
  arche-browser --headless           # Run Chrome headless
  arche-browser --reset-token        # Generate new auth token

Local MCP (Claude Code settings):
  {"command": "arche-browser"}

Remote MCP with auth (Claude Code settings):
  {"url": "http://HOST:8080/sse?token=YOUR_TOKEN"}
        """
    )

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
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome in headless mode"
    )
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

    transport = "sse" if args.sse else "stdio"
    run(
        transport=transport,
        port=args.port,
        headless=args.headless,
        auth=not args.no_auth,
        token=args.token
    )


if __name__ == "__main__":
    main()
