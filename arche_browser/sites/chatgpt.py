"""
ChatGPT client built on Browser automation.

Usage:
    from arche_browser.sites import ChatGPT

    client = ChatGPT("localhost:9222")
    response = client.send("Hello!")
    print(response)
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Iterator

from ..browser import Browser


class ChatGPTUI:
    """UI automation for ChatGPT (bypasses bot detection)."""

    def __init__(self, browser: Browser):
        self.browser = browser

    def type_message(self, text: str) -> bool:
        """Type message into ChatGPT input."""
        return self.browser.eval(f"""
            (() => {{
                const el = document.querySelector('#prompt-textarea');
                if (!el) return false;
                el.focus();
                el.innerHTML = '<p>' + {json.dumps(text)} + '</p>';
                el.dispatchEvent(new InputEvent('input', {{
                    bubbles: true, inputType: 'insertText', data: {json.dumps(text)}
                }}));
                return true;
            }})()
        """) or False

    def click_send(self) -> bool:
        """Click send button."""
        return self.browser.eval("""
            (() => {
                const btn = document.querySelector('[data-testid="send-button"]');
                if (btn && !btn.disabled) { btn.click(); return true; }
                const el = document.querySelector('#prompt-textarea');
                if (el) {
                    el.dispatchEvent(new KeyboardEvent('keydown', {
                        key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true
                    }));
                    return true;
                }
                return false;
            })()
        """) or False

    def wait_response(self, timeout: int = 120) -> str:
        """Wait for and return assistant response."""
        start = time.time()
        last_text = ""

        while time.time() - start < timeout:
            is_streaming = self.browser.query('[data-testid="stop-button"]')
            text = self.browser.eval("""
                (() => {
                    const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
                    if (!msgs.length) return '';
                    const last = msgs[msgs.length - 1];
                    const md = last.querySelector('.markdown');
                    return md ? md.innerText : last.innerText;
                })()
            """) or ""

            if not is_streaming and text and text == last_text:
                return text

            last_text = text
            time.sleep(0.5)

        return last_text

    def send(self, text: str, wait: bool = True) -> str:
        """Send message and optionally wait for response."""
        if not self.type_message(text):
            raise RuntimeError("Could not find input field")
        time.sleep(0.3)
        self.click_send()
        if wait:
            time.sleep(1)
            return self.wait_response()
        return ""


class ChatGPT:
    """
    ChatGPT client with full API access.

    Features:
    - User info, models, conversations
    - Memories, custom instructions
    - GPTs discovery
    - Message sending (UI-based to bypass bot detection)

    Example:
        client = ChatGPT("localhost:9222")
        print(client.user)
        print(client.models())
        response = client.send("Tell me a joke")
    """

    BASE = "https://chatgpt.com"

    def __init__(self, address: str = "localhost:9222"):
        self._browser = Browser(address)
        self._ui = ChatGPTUI(self._browser)
        self._token: Optional[str] = None
        self._token_exp: float = 0

    def close(self):
        self._browser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ─── Auth ───────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Get access token (cached)."""
        if self._token and time.time() < self._token_exp:
            return self._token

        data = self._browser.get("/api/auth/session", base=self.BASE)
        self._token = data.get("accessToken", "")
        self._token_exp = time.time() + 3500
        return self._token

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    # ─── Generic API ────────────────────────────────────────────────

    def get(self, path: str) -> Any:
        return self._browser.get(path, headers=self._headers(), base=self.BASE)

    def post(self, path: str, data: Optional[Dict] = None) -> Any:
        return self._browser.post(path, data or {}, headers=self._headers(), base=self.BASE)

    def patch(self, path: str, data: Dict) -> Any:
        return self._browser.patch(path, data, headers=self._headers(), base=self.BASE)

    def delete(self, path: str) -> bool:
        result = self._browser.delete(path, headers=self._headers(), base=self.BASE)
        return not (result or {}).get("error")

    # ─── User ───────────────────────────────────────────────────────

    @property
    def user(self) -> Dict:
        """Get current user info."""
        return self.get("/backend-api/me")

    # ─── Models ─────────────────────────────────────────────────────

    def models(self) -> List[Dict]:
        """List available models."""
        return self.get("/backend-api/models").get("models", [])

    # ─── Conversations ──────────────────────────────────────────────

    def conversations(self, limit: int = 28, offset: int = 0) -> List[Dict]:
        """List conversations."""
        return self.get(
            f"/backend-api/conversations?offset={offset}&limit={limit}&order=updated"
        ).get("items", [])

    def conversation(self, id: str) -> Dict:
        """Get conversation by ID."""
        return self.get(f"/backend-api/conversation/{id}")

    def delete_conversation(self, id: str) -> bool:
        """Delete conversation."""
        return self.patch(f"/backend-api/conversation/{id}", {"is_visible": False}).get("success", False)

    def rename_conversation(self, id: str, title: str) -> bool:
        """Rename conversation."""
        return self.patch(f"/backend-api/conversation/{id}", {"title": title}).get("success", False)

    # ─── Memories ───────────────────────────────────────────────────

    def memories(self) -> List[Dict]:
        """List memories."""
        return self.get("/backend-api/memories").get("memories", [])

    def delete_memory(self, id: str) -> bool:
        """Delete memory."""
        return self.delete(f"/backend-api/memories/{id}")

    def clear_memories(self) -> bool:
        """Clear all memories."""
        return self.delete("/backend-api/memories")

    # ─── Custom Instructions ────────────────────────────────────────

    def instructions(self) -> Dict:
        """Get custom instructions."""
        return self.get("/backend-api/user_system_messages")

    def set_instructions(
        self,
        about_user: Optional[str] = None,
        about_model: Optional[str] = None,
        enabled: bool = True
    ) -> bool:
        """Set custom instructions."""
        current = self.instructions()
        data = {
            "enabled": enabled,
            "about_user_message": about_user if about_user is not None else current.get("about_user_message", ""),
            "about_model_message": about_model if about_model is not None else current.get("about_model_message", "")
        }
        return "enabled" in self.post("/backend-api/user_system_messages", data)

    # ─── Settings ───────────────────────────────────────────────────

    def beta_features(self) -> Dict[str, bool]:
        """Get beta features status."""
        return self.get("/backend-api/settings/beta_features")

    def set_beta_feature(self, name: str, enabled: bool) -> bool:
        """Enable/disable beta feature."""
        return name in self.post("/backend-api/settings/beta_features", {name: enabled})

    # ─── GPTs ───────────────────────────────────────────────────────

    def discover_gpts(self, limit: int = 10) -> List[Dict]:
        """Discover GPTs."""
        data = self.get(f"/backend-api/gizmos/discovery?limit={limit}")
        gpts = []
        for cat in data.get("categories", []):
            for g in cat.get("gizmos", []):
                gpts.append({
                    "id": g.get("id"),
                    "name": g.get("display", {}).get("name"),
                    "description": g.get("display", {}).get("description"),
                })
        return gpts

    # ─── Messaging ──────────────────────────────────────────────────

    def send(self, message: str, wait: bool = True) -> str:
        """
        Send message via UI automation (bypasses bot detection).

        Args:
            message: Message to send
            wait: Whether to wait for response

        Returns:
            Assistant's response text
        """
        return self._ui.send(message, wait)

    def stream(
        self,
        message: str,
        model: str = "auto",
        conversation_id: Optional[str] = None
    ) -> Iterator[str]:
        """
        Stream message via API (may trigger bot detection).

        Args:
            message: Message to send
            model: Model to use
            conversation_id: Continue existing conversation

        Yields:
            Response text chunks
        """
        msg_id = str(uuid.uuid4())
        parent_id = str(uuid.uuid4())

        if conversation_id:
            conv = self.conversation(conversation_id)
            parent_id = conv.get("current_node", parent_id)

        payload = {
            "action": "next",
            "messages": [{
                "id": msg_id,
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": [message]},
                "metadata": {}
            }],
            "parent_message_id": parent_id,
            "model": model,
            "conversation_mode": {"kind": "primary_assistant"},
            "websocket_request_id": str(uuid.uuid4())
        }

        if conversation_id:
            payload["conversation_id"] = conversation_id

        # Get sentinel token
        sentinel = self.post("/backend-api/sentinel/chat-requirements", {})
        headers = {**self._headers()}
        if sentinel.get("token"):
            headers["openai-sentinel-chat-requirements-token"] = sentinel["token"]

        result = self._browser.eval(f"""
            (async () => {{
                const payload = {json.dumps(payload)};
                const headers = {json.dumps({**headers, "Content-Type": "application/json"})};
                const resp = await fetch('{self.BASE}/backend-api/conversation', {{
                    method: 'POST', credentials: 'include', headers, body: JSON.stringify(payload)
                }});
                if (resp.status !== 200) return JSON.stringify({{error: await resp.text()}});
                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let text = '';
                while (true) {{
                    const {{done, value}} = await reader.read();
                    if (done) break;
                    for (const line of decoder.decode(value).split('\\n')) {{
                        if (line.startsWith('data: ') && !line.includes('[DONE]')) {{
                            try {{
                                const d = JSON.parse(line.slice(6));
                                const parts = d.message?.content?.parts;
                                if (parts?.[0]) text = parts[0];
                            }} catch {{}}
                        }}
                    }}
                }}
                return JSON.stringify({{text}});
            }})()
        """, timeout=300)

        if result:
            if result.get("error"):
                raise RuntimeError(result["error"][:200])
            yield result.get("text", "")

    # ─── Aliases ────────────────────────────────────────────────────

    def chat(self, message: str, **kwargs) -> str:
        """Alias for send()."""
        return self.send(message, **kwargs)

    def ask(self, message: str, **kwargs) -> str:
        """Alias for send()."""
        return self.send(message, **kwargs)
