#!/usr/bin/env python3
"""
Test remote MCP SSE connection to Windows server.
"""

import json
import requests
import threading
import time
import queue
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class MCPClient:
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

    def _sse_reader(self):
        try:
            print(f"[SSE] Connecting to {self._sse_url()}")
            resp = requests.get(
                self._sse_url(),
                stream=True,
                verify=False,
                timeout=60
            )
            print(f"[SSE] Status: {resp.status_code}")

            event_type = None
            data_lines = []

            for line in resp.iter_lines(decode_unicode=True):
                if self._stop.is_set():
                    break
                if line is None:
                    continue

                line = line.strip()
                if not line:
                    if event_type and data_lines:
                        data = "\n".join(data_lines)
                        self.events.put((event_type, data))
                    event_type = None
                    data_lines = []
                    continue

                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())

        except Exception as e:
            print(f"[SSE Error] {e}")

    def connect(self, timeout: float = 15) -> bool:
        self._thread = threading.Thread(target=self._sse_reader, daemon=True)
        self._thread.start()

        start = time.time()
        while time.time() - start < timeout:
            try:
                event_type, data = self.events.get(timeout=1)
                print(f"[Event] {event_type}: {data}")

                if event_type == "endpoint":
                    self.session_url = f"{self.base_url}{data}"
                    print(f"[OK] Session: {self.session_url}")
                    return True
                elif event_type == "message":
                    try:
                        msg = json.loads(data)
                        if "id" in msg:
                            self.responses[msg["id"]] = msg
                    except:
                        pass
            except queue.Empty:
                continue

        print("[Error] Timeout waiting for endpoint")
        return False

    def call(self, method: str, params: dict = None, timeout: float = 30) -> dict:
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

        # Add token to POST URL
        post_url = self.session_url
        if self.token:
            sep = "&" if "?" in post_url else "?"
            post_url += f"{sep}token={self.token}"

        print(f"[>] {method}...")
        resp = requests.post(post_url, json=request, verify=False, timeout=15)
        print(f"[POST] {resp.status_code}")

        start = time.time()
        while time.time() - start < timeout:
            if msg_id in self.responses:
                return self.responses.pop(msg_id)

            try:
                event_type, data = self.events.get(timeout=1)
                if event_type == "message":
                    try:
                        msg = json.loads(data)
                        if msg.get("id") == msg_id:
                            return msg
                        elif "id" in msg:
                            self.responses[msg["id"]] = msg
                    except:
                        pass
            except queue.Empty:
                continue

        raise TimeoutError(f"Timeout for {method}")

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def main():
    print("=" * 50)
    print("MCP Remote Client Test - Windows Server")
    print("=" * 50)

    # Connect to Windows server
    BASE_URL = "https://192.168.0.14:8080"
    TOKEN = "BWaZrpvJXeuuQ4clqlDhknEIPnnVhi-Id_xD92XKOdI"

    client = MCPClient(BASE_URL, TOKEN)

    print("\n[1] Connecting...")
    if not client.connect():
        print("Failed!")
        return

    print("\n[2] Initialize...")
    resp = client.call("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "arche-test", "version": "1.0"}
    })
    print(f"  Server: {resp.get('result', {}).get('serverInfo', {})}")

    print("\n[3] Get current URL...")
    resp = client.call("tools/call", {"name": "get_url", "arguments": {}})
    if "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            print(f"  Current URL: {content[0].get('text')}")

    print("\n[4] Get title...")
    resp = client.call("tools/call", {"name": "get_title", "arguments": {}})
    if "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            print(f"  Title: {content[0].get('text')}")

    print("\n[5] Navigate to naver.com...")
    resp = client.call("tools/call", {
        "name": "goto",
        "arguments": {"url": "https://naver.com"}
    })
    if "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            print(f"  Navigated to: {content[0].get('text')}")

    print("\n[6] Get new title...")
    resp = client.call("tools/call", {"name": "get_title", "arguments": {}})
    if "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            print(f"  Title: {content[0].get('text')}")

    print("\n[7] Take screenshot...")
    resp = client.call("tools/call", {"name": "screenshot", "arguments": {}})
    if "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            b64 = content[0].get("text", "")
            print(f"  Screenshot base64 length: {len(b64)}")
            # Save to file
            if len(b64) > 100:
                import base64
                with open("/tmp/remote_screenshot.png", "wb") as f:
                    f.write(base64.b64decode(b64))
                print("  Saved to /tmp/remote_screenshot.png")

    client.close()
    print("\n" + "=" * 50)
    print("Done!")
    print("=" * 50)


if __name__ == "__main__":
    main()
