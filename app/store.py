"""Small SQLite store for idempotency and ordering.

- processed_events: Stripe event IDs already applied. Stripe delivers at least once,
  so the same event can arrive twice; a repeat is skipped.
- object_versions: newest event timestamp applied per object. Stripe does not
  guarantee order, so an older event arriving late is skipped instead of
  overwriting newer data.
"""
import sqlite3
import threading
import time


class EventStore:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS processed_events ("
                " event_id TEXT PRIMARY KEY, event_type TEXT, result TEXT, processed_at REAL)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS object_versions ("
                " object_key TEXT PRIMARY KEY, last_event_created INTEGER)")
            # Stripe ID -> HubSpot ID. HubSpot search is eventually consistent (a record
            # can take seconds to become searchable), so we remember what we created.
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS links ("
                " stripe_id TEXT PRIMARY KEY, hubspot_id TEXT)")
        self._key_locks = {}

    def lock_for(self, key: str) -> threading.Lock:
        """One lock per object, so two events about the same subscription never run at once."""
        with self._lock:
            return self._key_locks.setdefault(key, threading.Lock())

    def get_link(self, stripe_id: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT hubspot_id FROM links WHERE stripe_id = ?", (stripe_id,)).fetchone()
        return row[0] if row else None

    def set_link(self, stripe_id: str, hubspot_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO links VALUES (?, ?)", (stripe_id, hubspot_id))

    def seen(self, event_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM processed_events WHERE event_id = ?", (event_id,)).fetchone()
        return row is not None

    def mark(self, event_id: str, event_type: str, result: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO processed_events VALUES (?, ?, ?, ?)",
                (event_id, event_type, result, time.time()))

    def is_stale(self, object_key: str, created: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_event_created FROM object_versions WHERE object_key = ?",
                (object_key,)).fetchone()
        return row is not None and created < row[0]

    def touch(self, object_key: str, created: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO object_versions VALUES (?, ?) ON CONFLICT(object_key) DO UPDATE"
                " SET last_event_created = MAX(last_event_created, excluded.last_event_created)",
                (object_key, created))
