"""
Browser History Access

Reads Chrome browsing history from SQLite database in read-only mode
to avoid lock conflicts with running browser.
"""

import os
import sqlite3
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class HistoryItem:
    """A browser history entry."""
    url: str
    title: str
    visit_time: datetime
    visit_count: int
    typed_count: int  # Times URL was typed directly
    last_visit_time: datetime


@dataclass
class VisitItem:
    """A single visit to a URL."""
    url: str
    title: str
    visit_time: datetime
    transition: str  # link, typed, auto_bookmark, etc.
    from_url: Optional[str] = None


# Chrome timestamp epoch: Jan 1, 1601
CHROME_EPOCH = datetime(1601, 1, 1)


def chrome_time_to_datetime(chrome_time: int) -> datetime:
    """Convert Chrome's microsecond timestamp to datetime."""
    if not chrome_time:
        return datetime.min
    # Chrome stores time as microseconds since Jan 1, 1601
    return CHROME_EPOCH + timedelta(microseconds=chrome_time)


def datetime_to_chrome_time(dt: datetime) -> int:
    """Convert datetime to Chrome's microsecond timestamp."""
    delta = dt - CHROME_EPOCH
    return int(delta.total_seconds() * 1_000_000)


# Transition type mapping
TRANSITION_TYPES = {
    0: "link",           # User clicked a link
    1: "typed",          # User typed URL
    2: "auto_bookmark",  # Automatic navigation from bookmark
    3: "auto_subframe",  # Subframe navigation
    4: "manual_subframe",
    5: "generated",      # Generated from form submission
    6: "auto_toplevel",
    7: "form_submit",
    8: "reload",
    9: "keyword",        # Omnibox keyword search
    10: "keyword_generated",
}


def get_chrome_history_path() -> Optional[Path]:
    """Find Chrome history database path."""
    # Common locations by platform
    home = Path.home()

    candidates = [
        # Linux
        home / ".config/google-chrome/Default/History",
        home / ".config/chromium/Default/History",
        home / ".config/google-chrome-beta/Default/History",
        # macOS
        home / "Library/Application Support/Google/Chrome/Default/History",
        home / "Library/Application Support/Chromium/Default/History",
        # Windows (via WSL or native)
        home / "AppData/Local/Google/Chrome/User Data/Default/History",
    ]

    for path in candidates:
        if path.exists():
            return path

    return None


class BrowserHistory:
    """
    Read-only access to Chrome browsing history.

    Uses immutable mode and WAL checkpoint to avoid lock conflicts.
    """

    def __init__(self, history_path: Optional[str] = None):
        """
        Initialize history reader.

        Args:
            history_path: Path to History SQLite file.
                         If None, auto-detect Chrome's default location.
        """
        if history_path:
            self.db_path = Path(history_path)
        else:
            self.db_path = get_chrome_history_path()

        if not self.db_path or not self.db_path.exists():
            raise FileNotFoundError(
                f"Chrome history database not found. "
                f"Searched: {self.db_path or 'default locations'}"
            )

        self._conn: Optional[sqlite3.Connection] = None
        self._temp_dir: Optional[str] = None

    def _connect(self) -> sqlite3.Connection:
        """
        Connect to history database in read-only mode.

        Uses URI with immutable flag to prevent any locking.
        """
        if self._conn:
            return self._conn

        # Use immutable mode to completely avoid locks
        # This reads the file as-is without any journal checking
        uri = f"file:{self.db_path}?mode=ro&immutable=1"

        try:
            self._conn = sqlite3.connect(uri, uri=True, timeout=5.0)
            self._conn.row_factory = sqlite3.Row
            return self._conn
        except sqlite3.OperationalError as e:
            # If immutable fails (rare), try with a temp copy
            if "readonly" in str(e).lower() or "locked" in str(e).lower():
                return self._connect_via_copy()
            raise

    def _connect_via_copy(self) -> sqlite3.Connection:
        """Fallback: copy database to temp location."""
        self._temp_dir = tempfile.mkdtemp(prefix="chrome_history_")
        temp_db = Path(self._temp_dir) / "History"

        shutil.copy2(self.db_path, temp_db)

        # Also copy WAL and SHM if they exist
        for ext in ["-wal", "-shm"]:
            src = Path(str(self.db_path) + ext)
            if src.exists():
                shutil.copy2(src, Path(str(temp_db) + ext))

        self._conn = sqlite3.connect(str(temp_db), timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        """Close database connection and cleanup temp files."""
        if self._conn:
            self._conn.close()
            self._conn = None
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def search(
        self,
        query: str = "",
        max_results: int = 100,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[HistoryItem]:
        """
        Search browsing history.

        Args:
            query: Text to search in URL and title (empty = all)
            max_results: Maximum number of results
            start_time: Filter visits after this time
            end_time: Filter visits before this time

        Returns:
            List of HistoryItem sorted by last visit time (newest first)
        """
        conn = self._connect()

        sql = """
            SELECT url, title, visit_count, typed_count, last_visit_time
            FROM urls
            WHERE 1=1
        """
        params: List[Any] = []

        if query:
            sql += " AND (url LIKE ? OR title LIKE ?)"
            like_query = f"%{query}%"
            params.extend([like_query, like_query])

        if start_time:
            sql += " AND last_visit_time >= ?"
            params.append(datetime_to_chrome_time(start_time))

        if end_time:
            sql += " AND last_visit_time <= ?"
            params.append(datetime_to_chrome_time(end_time))

        sql += " ORDER BY last_visit_time DESC LIMIT ?"
        params.append(max_results)

        cursor = conn.execute(sql, params)
        results = []

        for row in cursor:
            last_visit = chrome_time_to_datetime(row["last_visit_time"])
            results.append(HistoryItem(
                url=row["url"],
                title=row["title"] or "",
                visit_time=last_visit,
                visit_count=row["visit_count"],
                typed_count=row["typed_count"],
                last_visit_time=last_visit,
            ))

        return results

    def get_visits(
        self,
        url: str,
        max_results: int = 50
    ) -> List[VisitItem]:
        """
        Get all visits to a specific URL.

        Args:
            url: URL to get visits for
            max_results: Maximum number of visits

        Returns:
            List of VisitItem sorted by visit time (newest first)
        """
        conn = self._connect()

        sql = """
            SELECT
                u.url,
                u.title,
                v.visit_time,
                v.transition,
                v.from_visit
            FROM visits v
            JOIN urls u ON v.url = u.id
            WHERE u.url = ?
            ORDER BY v.visit_time DESC
            LIMIT ?
        """

        cursor = conn.execute(sql, [url, max_results])
        results = []

        for row in cursor:
            # Decode transition type (stored as flags)
            transition_type = row["transition"] & 0xFF
            transition = TRANSITION_TYPES.get(transition_type, "other")

            # Get referring URL if available
            from_url = None
            if row["from_visit"]:
                from_cursor = conn.execute("""
                    SELECT u.url FROM visits v
                    JOIN urls u ON v.url = u.id
                    WHERE v.id = ?
                """, [row["from_visit"]])
                from_row = from_cursor.fetchone()
                if from_row:
                    from_url = from_row["url"]

            results.append(VisitItem(
                url=row["url"],
                title=row["title"] or "",
                visit_time=chrome_time_to_datetime(row["visit_time"]),
                transition=transition,
                from_url=from_url,
            ))

        return results

    def recent(
        self,
        hours: int = 24,
        max_results: int = 100
    ) -> List[HistoryItem]:
        """
        Get recently visited URLs.

        Args:
            hours: Hours to look back
            max_results: Maximum results

        Returns:
            List of HistoryItem
        """
        start_time = datetime.now() - timedelta(hours=hours)
        return self.search(query="", max_results=max_results, start_time=start_time)

    def most_visited(
        self,
        max_results: int = 50,
        days: int = 30
    ) -> List[HistoryItem]:
        """
        Get most visited URLs.

        Args:
            max_results: Maximum results
            days: Only count visits in last N days

        Returns:
            List of HistoryItem sorted by visit count
        """
        conn = self._connect()
        start_time = datetime.now() - timedelta(days=days)

        sql = """
            SELECT
                u.url,
                u.title,
                COUNT(v.id) as visit_count,
                u.typed_count,
                MAX(v.visit_time) as last_visit_time
            FROM urls u
            JOIN visits v ON v.url = u.id
            WHERE v.visit_time >= ?
            GROUP BY u.id
            ORDER BY visit_count DESC
            LIMIT ?
        """

        cursor = conn.execute(sql, [
            datetime_to_chrome_time(start_time),
            max_results
        ])

        results = []
        for row in cursor:
            last_visit = chrome_time_to_datetime(row["last_visit_time"])
            results.append(HistoryItem(
                url=row["url"],
                title=row["title"] or "",
                visit_time=last_visit,
                visit_count=row["visit_count"],
                typed_count=row["typed_count"],
                last_visit_time=last_visit,
            ))

        return results

    def domains(
        self,
        max_results: int = 50,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get most visited domains.

        Args:
            max_results: Maximum results
            days: Only count visits in last N days

        Returns:
            List of dicts with domain, visit_count, page_count
        """
        conn = self._connect()
        start_time = datetime.now() - timedelta(days=days)

        # Extract domain from URL using SQLite
        sql = """
            SELECT
                SUBSTR(
                    SUBSTR(u.url, INSTR(u.url, '://') + 3),
                    1,
                    CASE
                        WHEN INSTR(SUBSTR(u.url, INSTR(u.url, '://') + 3), '/') > 0
                        THEN INSTR(SUBSTR(u.url, INSTR(u.url, '://') + 3), '/') - 1
                        ELSE LENGTH(SUBSTR(u.url, INSTR(u.url, '://') + 3))
                    END
                ) as domain,
                COUNT(DISTINCT v.id) as visit_count,
                COUNT(DISTINCT u.id) as page_count
            FROM urls u
            JOIN visits v ON v.url = u.id
            WHERE v.visit_time >= ?
                AND u.url LIKE 'http%'
            GROUP BY domain
            ORDER BY visit_count DESC
            LIMIT ?
        """

        cursor = conn.execute(sql, [
            datetime_to_chrome_time(start_time),
            max_results
        ])

        return [
            {
                "domain": row["domain"],
                "visit_count": row["visit_count"],
                "page_count": row["page_count"],
            }
            for row in cursor
        ]
