#!/usr/bin/env python3
"""
Extensive browser control test via MCP SSE.
"""

import json
import requests
import threading
import time
import queue
import base64
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
            resp = requests.get(self._sse_url(), stream=True, verify=False, timeout=120)
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
                        self.events.put((event_type, "\n".join(data_lines)))
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
                if event_type == "endpoint":
                    self.session_url = f"{self.base_url}{data}"
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
        return False

    def call(self, method: str, params: dict = None, timeout: float = 30) -> dict:
        if not self.session_url:
            raise RuntimeError("Not connected")
        self._id_counter += 1
        msg_id = self._id_counter
        request = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}
        post_url = self.session_url
        if self.token:
            sep = "&" if "?" in post_url else "?"
            post_url += f"{sep}token={self.token}"
        requests.post(post_url, json=request, verify=False, timeout=15)
        start = time.time()
        while time.time() - start < timeout:
            if msg_id in self.responses:
                return self.responses.pop(msg_id)
            try:
                event_type, data = self.events.get(timeout=0.5)
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

    def tool(self, name: str, **kwargs) -> any:
        """Call a tool and return the result text."""
        resp = self.call("tools/call", {"name": name, "arguments": kwargs})
        if "result" in resp:
            content = resp["result"].get("content", [])
            if content:
                return content[0].get("text")
        if "error" in resp:
            return f"ERROR: {resp['error']}"
        return None

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def save_screenshot(client, filename):
    b64 = client.tool("screenshot")
    if b64 and len(b64) > 100:
        with open(filename, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"  📸 Saved: {filename}")
        return True
    return False


def main():
    print("=" * 60)
    print("🚀 BROWSER CONTROL TEST - Windows Remote Server")
    print("=" * 60)

    BASE_URL = "https://192.168.0.14:8080"
    TOKEN = "BWaZrpvJXeuuQ4clqlDhknEIPnnVhi-Id_xD92XKOdI"

    client = MCPClient(BASE_URL, TOKEN)

    print("\n[1] 🔗 Connecting...")
    if not client.connect():
        print("Failed!")
        return
    print("  ✅ Connected!")

    # Initialize
    client.call("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "control-test", "version": "1.0"}
    })

    # ========================================
    print("\n[2] 🌐 Go to Google...")
    url = client.tool("goto", url="https://google.com")
    print(f"  URL: {url}")
    time.sleep(2)
    save_screenshot(client, "/tmp/01_google.png")

    # ========================================
    print("\n[3] 🔍 Search on Google...")
    # Type in search box
    client.tool("type_text", selector='textarea[name="q"]', text="Python MCP protocol")
    time.sleep(1)
    save_screenshot(client, "/tmp/02_google_typed.png")

    # Press Enter to search
    client.tool("key_press", key="Enter")
    time.sleep(3)
    title = client.tool("get_title")
    print(f"  Title: {title}")
    save_screenshot(client, "/tmp/03_google_results.png")

    # ========================================
    print("\n[4] 📺 Go to YouTube...")
    client.tool("goto", url="https://youtube.com")
    time.sleep(3)
    title = client.tool("get_title")
    print(f"  Title: {title}")
    save_screenshot(client, "/tmp/04_youtube.png")

    # ========================================
    print("\n[5] 🔍 Search YouTube...")
    client.tool("type_text", selector='input[name="search_query"]', text="lofi hip hop")
    time.sleep(1)
    client.tool("key_press", key="Enter")
    time.sleep(3)
    save_screenshot(client, "/tmp/05_youtube_search.png")

    # ========================================
    print("\n[6] 📜 Scroll down...")
    client.tool("scroll_to", x=0, y=500)
    time.sleep(1)
    save_screenshot(client, "/tmp/06_youtube_scrolled.png")

    # ========================================
    print("\n[7] 🐙 Go to GitHub...")
    client.tool("goto", url="https://github.com")
    time.sleep(2)
    title = client.tool("get_title")
    print(f"  Title: {title}")
    save_screenshot(client, "/tmp/07_github.png")

    # ========================================
    print("\n[8] 🔍 Search GitHub...")
    client.tool("type_text", selector='input[name="q"]', text="mcp server python")
    time.sleep(1)
    client.tool("key_press", key="Enter")
    time.sleep(3)
    save_screenshot(client, "/tmp/08_github_search.png")

    # ========================================
    print("\n[9] 📰 Go to Hacker News...")
    client.tool("goto", url="https://news.ycombinator.com")
    time.sleep(2)
    title = client.tool("get_title")
    print(f"  Title: {title}")
    save_screenshot(client, "/tmp/09_hackernews.png")

    # ========================================
    print("\n[10] 🇰🇷 Go to Daum...")
    client.tool("goto", url="https://daum.net")
    time.sleep(2)
    title = client.tool("get_title")
    print(f"  Title: {title}")
    save_screenshot(client, "/tmp/10_daum.png")

    # ========================================
    print("\n[11] 📊 Get performance metrics...")
    metrics = client.tool("get_performance_metrics")
    print(f"  Metrics: {metrics[:200] if metrics else 'N/A'}...")

    # ========================================
    print("\n[12] 🖥️ Set viewport to mobile...")
    client.tool("set_viewport", width=375, height=812, mobile=True)
    time.sleep(1)
    save_screenshot(client, "/tmp/11_mobile_view.png")

    # ========================================
    print("\n[13] 🖥️ Back to desktop...")
    client.tool("set_viewport", width=1920, height=1080, mobile=False)
    time.sleep(1)

    # ========================================
    print("\n[14] 🏠 Final - Naver...")
    client.tool("goto", url="https://naver.com")
    time.sleep(2)
    save_screenshot(client, "/tmp/12_final_naver.png")

    # List all screenshots
    print("\n" + "=" * 60)
    print("📸 Screenshots saved:")
    import os
    for f in sorted(os.listdir("/tmp")):
        if f.endswith(".png") and f.startswith(("01_", "02_", "03_", "04_", "05_", "06_", "07_", "08_", "09_", "10_", "11_", "12_")):
            size = os.path.getsize(f"/tmp/{f}")
            print(f"  /tmp/{f} ({size//1024}KB)")

    client.close()
    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
