"""
Shared Utilities

Common utility functions used across modules.
"""

from typing import Optional, Tuple


def box_center(content: list) -> Optional[Tuple[int, int]]:
    """
    Get center point from CDP box model content array.

    CDP DOM.getBoxModel returns content as [x1,y1, x2,y1, x2,y2, x1,y2]
    (clockwise from top-left).

    Args:
        content: Box model content array (8 elements)

    Returns:
        (x, y) center point, or None if invalid
    """
    if not content or len(content) < 8:
        return None
    # content: [x1,y1, x2,y1, x2,y2, x1,y2]
    x = int((content[0] + content[4]) / 2)  # (x1 + x2) / 2
    y = int((content[1] + content[5]) / 2)  # (y1 + y2) / 2
    return x, y


def truncate(text: str, max_len: int = 80, suffix: str = "...") -> str:
    """Truncate text with suffix if too long."""
    if not text or len(text) <= max_len:
        return text or ""
    return text[:max_len - len(suffix)] + suffix


def paginate(items: list, page_idx: int = 0, page_size: int = 50) -> Tuple[list, int, int, bool]:
    """
    Paginate a list of items.

    Args:
        items: List to paginate
        page_idx: Page index (0-based)
        page_size: Items per page

    Returns:
        (page_items, start_idx, end_idx, has_more)
    """
    total = len(items)
    start = page_idx * page_size
    end = min(start + page_size, total)
    return items[start:end], start, end, end < total
