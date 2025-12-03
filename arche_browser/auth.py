"""
Token-based authentication for remote MCP access.

Usage:
    # Server generates token on first run
    arche-browser --sse --port 8080
    # Token: abc123... (saved to ~/.arche-browser/token)

    # Client connects with token
    {"url": "http://host:8080/sse", "headers": {"Authorization": "Bearer abc123..."}}
"""

import secrets
from pathlib import Path
from typing import Optional


class TokenAuth:
    """Simple token-based authentication."""

    TOKEN_FILE = Path.home() / ".arche-browser" / "token"
    TOKEN_LENGTH = 32

    def __init__(self, token: Optional[str] = None):
        self._token = token

    @property
    def token(self) -> str:
        """Get or create token."""
        if self._token:
            return self._token

        # Try to load existing token
        if self.TOKEN_FILE.exists():
            self._token = self.TOKEN_FILE.read_text().strip()
            return self._token

        # Generate new token
        self._token = self.generate()
        return self._token

    @classmethod
    def generate(cls, save: bool = True) -> str:
        """Generate new random token."""
        token = secrets.token_urlsafe(cls.TOKEN_LENGTH)
        if save:
            cls.TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            cls.TOKEN_FILE.write_text(token)
            cls.TOKEN_FILE.chmod(0o600)
        return token

    @classmethod
    def load(cls) -> Optional[str]:
        """Load token from file."""
        if cls.TOKEN_FILE.exists():
            return cls.TOKEN_FILE.read_text().strip()
        return None

    @classmethod
    def reset(cls) -> str:
        """Reset token (generate new one)."""
        if cls.TOKEN_FILE.exists():
            cls.TOKEN_FILE.unlink()
        return cls.generate()

    def verify(self, provided: str) -> bool:
        """Verify provided token."""
        if not provided:
            return False
        # Constant-time comparison
        expected = self.token
        if len(provided) != len(expected):
            return False
        result = 0
        for a, b in zip(provided.encode(), expected.encode()):
            result |= a ^ b
        return result == 0


def create_auth_middleware(auth: TokenAuth, require_auth: bool = True):
    """Create FastMCP authentication middleware."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Skip auth for health check
            if request.url.path == "/health":
                return await call_next(request)

            if require_auth:
                # Get token from Authorization header
                auth_header = request.headers.get("Authorization", "")
                token = ""

                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]

                # Also check query param for SSE clients that can't set headers
                if not token:
                    token = request.query_params.get("token", "")

                if not auth.verify(token):
                    return JSONResponse(
                        {"error": "Unauthorized - Invalid or missing token"},
                        status_code=401
                    )

            return await call_next(request)

    return AuthMiddleware
