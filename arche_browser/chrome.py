"""
Chrome process management.

Usage:
    chrome = Chrome()
    chrome.start()
    # ... use browser ...
    chrome.stop()
"""

import os
import signal
import socket
import shutil
import platform
import subprocess
import time
from pathlib import Path
from typing import Optional


def find_chrome() -> str:
    """Find Chrome executable for current OS."""
    system = platform.system()

    if system == "Darwin":
        paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    elif system == "Windows":
        paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ]
    else:  # Linux
        paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]
        for name in ["google-chrome", "chromium", "chromium-browser"]:
            if path := shutil.which(name):
                paths.insert(0, path)

    for path in paths:
        if os.path.exists(path):
            return path

    raise FileNotFoundError("Chrome not found")


class Chrome:
    """Chrome process manager."""

    DEFAULT_PORT = 9222
    DEFAULT_PROFILE = Path.home() / ".arche-browser" / "profile"
    DEFAULT_HEADLESS = False  # Can be overridden before instantiation

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        headless: Optional[bool] = None,
        user_data_dir: Optional[Path] = None,
        chrome_path: Optional[str] = None,
    ):
        self.port = port
        self.headless = headless if headless is not None else self.DEFAULT_HEADLESS
        self.user_data_dir = user_data_dir or self.DEFAULT_PROFILE
        self.chrome_path = chrome_path or find_chrome()
        self.process: Optional[subprocess.Popen] = None

    def start(self, url: Optional[str] = None) -> "Chrome":
        """Start Chrome with remote debugging enabled."""
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        args = [
            self.chrome_path,
            f"--remote-debugging-port={self.port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={self.user_data_dir}",
        ]

        if self.headless:
            args.append("--headless=new")

        if url:
            args.append(url)

        # Platform-specific process creation
        kwargs = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["preexec_fn"] = os.setsid

        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs
        )

        self._wait_ready()
        return self

    def _wait_ready(self, timeout: int = 30):
        """Wait for Chrome to accept connections."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    s.connect(("127.0.0.1", self.port))
                    return
            except (socket.error, ConnectionRefusedError):
                time.sleep(0.2)
        raise TimeoutError(f"Chrome did not start within {timeout}s")

    def stop(self):
        """Stop Chrome process."""
        if self.process:
            try:
                if platform.system() == "Windows":
                    self.process.terminate()
                else:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
            except:
                self.process.kill()
            finally:
                self.process = None

    @property
    def running(self) -> bool:
        """Check if Chrome is running."""
        return self.process is not None and self.process.poll() is None

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()
