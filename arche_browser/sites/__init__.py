"""
Site-specific browser automation clients.

These modules provide high-level APIs for specific websites,
built on top of the core Browser class.
"""

from .chatgpt import ChatGPT

__all__ = ["ChatGPT"]
