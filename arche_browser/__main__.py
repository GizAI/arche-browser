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


def main():
    parser = argparse.ArgumentParser(
        prog="arche-browser",
        description="MCP Server for Browser Automation via Chrome DevTools Protocol",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  arche-browser                    # Run as stdio MCP server
  arche-browser --sse --port 8080  # Run as SSE server for remote
  arche-browser --headless         # Run Chrome headless

Local MCP (add to Claude Code settings):
  {"command": "arche-browser"}

Remote MCP (add to Claude Code settings):
  {"url": "http://YOUR_IP:8080/sse"}
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

    args = parser.parse_args()

    transport = "sse" if args.sse else "stdio"
    run(transport=transport, port=args.port, headless=args.headless)


if __name__ == "__main__":
    main()
