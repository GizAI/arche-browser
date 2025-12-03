#!/usr/bin/env python3
"""
Simple MCP SSE Client for testing arche-browser.
"""

import json
import requests
import threading
import time
import queue
import urllib3

# Disable SSL warnings for self-signed cert
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class MCPClient:
    """Simple MCP client over SSE transport."""

    def __init__(self, base_url: str, token: str = None):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.session_url = None
        self.events = queue.Queue()
        self.responses = {}
        self._stop = threading.Event()
        self._id_counter = 0
        self._thread = None

    def _sse_url(self) -> str:
        url = f"{self.base_url}/sse"
        if self.token:
            url += f"?token={self.token}"
        return url

    def _parse_sse(self, line: str) -> tuple:
        """Parse SSE line into (event_type, data)."""
        if line.startswith("event:"):
            return ("event", line[6:].strip())
        elif line.startswith("data:"):
            return ("data", line[5:].strip())
        return (None, None)

    def _sse_reader(self):
        """Background thread to read SSE stream."""
        try:
            resp = requests.get(
                self._sse_url(),
                stream=True,
                verify=False,
                timeout=60
            )

            event_type = None
            data_lines = []

            for line in resp.iter_lines(decode_unicode=True):
                if self._stop.is_set():
                    break

                if line is None:
                    continue

                line = line.strip()

                if not line:
                    # Empty line = end of event
                    if event_type and data_lines:
                        data = "\n".join(data_lines)
                        self.events.put((event_type, data))
                    event_type = None
                    data_lines = []
                    continue

                field, value = self._parse_sse(line)
                if field == "event":
                    event_type = value
                elif field == "data":
                    data_lines.append(value)

        except Exception as e:
            print(f"[SSE Reader Error] {e}")

    def connect(self, timeout: float = 10) -> bool:
        """Connect to SSE and get session URL."""
        self._thread = threading.Thread(target=self._sse_reader, daemon=True)
        self._thread.start()

        # Wait for endpoint event
        start = time.time()
        while time.time() - start < timeout:
            try:
                event_type, data = self.events.get(timeout=0.5)
                print(f"[Event] {event_type}: {data[:100]}...")

                if event_type == "endpoint":
                    # Parse the endpoint URL
                    self.session_url = f"{self.base_url}{data}"
                    print(f"[Connected] Session URL: {self.session_url}")
                    return True
                elif event_type == "message":
                    # JSON-RPC response
                    try:
                        msg = json.loads(data)
                        if "id" in msg:
                            self.responses[msg["id"]] = msg
                    except json.JSONDecodeError:
                        pass

            except queue.Empty:
                continue

        print("[Error] Timeout waiting for endpoint")
        return False

    def call(self, method: str, params: dict = None, timeout: float = 30) -> dict:
        """Call MCP method and wait for response."""
        if not self.session_url:
            raise RuntimeError("Not connected")

        self._id_counter += 1
        msg_id = self._id_counter

        request = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params or {}
        }

        # Send request
        resp = requests.post(
            self.session_url,
            json=request,
            verify=False,
            timeout=10
        )
        print(f"[POST] {resp.status_code}")

        # Wait for response in SSE stream
        start = time.time()
        while time.time() - start < timeout:
            # Check if we already have it
            if msg_id in self.responses:
                return self.responses.pop(msg_id)

            try:
                event_type, data = self.events.get(timeout=0.5)
                print(f"[Event] {event_type}: {data[:200]}...")

                if event_type == "message":
                    try:
                        msg = json.loads(data)
                        if msg.get("id") == msg_id:
                            return msg
                        elif "id" in msg:
                            self.responses[msg["id"]] = msg
                    except json.JSONDecodeError:
                        pass

            except queue.Empty:
                continue

        raise TimeoutError(f"No response for request {msg_id}")

    def close(self):
        """Close the connection."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def main():
    print("=== MCP Client Test ===\n")

    # Connect to local server (no auth)
    client = MCPClient("http://localhost:48080")

    print("[1] Connecting to SSE...")
    if not client.connect():
        print("Failed to connect!")
        return

    print("\n[2] Initialize...")
    resp = client.call("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0"}
    })
    print(f"Result: {json.dumps(resp, indent=2)[:500]}")

    print("\n[3] List tools...")
    resp = client.call("tools/list", {})
    if "result" in resp:
        tools = resp["result"].get("tools", [])
        print(f"Found {len(tools)} tools:")
        for t in tools[:5]:
            print(f"  - {t['name']}")
        if len(tools) > 5:
            print(f"  ... and {len(tools) - 5} more")

    print("\n[4] Call goto tool...")
    resp = client.call("tools/call", {
        "name": "goto",
        "arguments": {"url": "https://example.com"}
    })
    print(f"Result: {json.dumps(resp, indent=2)}")

    print("\n[5] Get title...")
    resp = client.call("tools/call", {
        "name": "get_title",
        "arguments": {}
    })
    print(f"Result: {json.dumps(resp, indent=2)}")

    print("\n[6] Take screenshot...")
    resp = client.call("tools/call", {
        "name": "screenshot",
        "arguments": {}
    })
    if "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            text = content[0].get("text", "")
            print(f"Screenshot base64 length: {len(text)}")

    client.close()
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
