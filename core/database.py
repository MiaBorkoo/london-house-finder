"""Database module for storing and managing property listings."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


def _utcnow() -> str:
    """Return current UTC time in SQLite-compatible format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
from pathlib import Path
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for storing property listings."""

    def __init__(self, db_path: str = "data/properties.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        db_dir = Path(self.db_path).parent
        if not db_dir.exists():
            db_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created database directory: {db_dir}")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS properties (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT,
                    price INTEGER,
                    bedrooms INTEGER,
                    bathrooms INTEGER,
                    property_type TEXT,
                    area TEXT,
                    address TEXT,
                    postcode TEXT,
                    url TEXT,
                    image_url TEXT,
                    description TEXT,
                    features TEXT,
                    sqm REAL DEFAULT 0,
                    sqm_source TEXT DEFAULT '',
                    epc_rating TEXT DEFAULT '',
                    lat REAL DEFAULT 0,
                    lon REAL DEFAULT 0,
                    tenure TEXT DEFAULT '',
                    floorplan_urls TEXT DEFAULT '[]',
                    has_garden INTEGER DEFAULT 0,
                    has_balcony INTEGER DEFAULT 0,
                    has_parking INTEGER DEFAULT 0,
                    is_chain_free INTEGER DEFAULT 0,
                    agent_name TEXT DEFAULT '',
                    agent_phone TEXT DEFAULT '',
                    nearest_station TEXT DEFAULT '',
                    walk_minutes REAL DEFAULT 0,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notified_instant TIMESTAMP,
                    notified_digest TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    notes TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scrape_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT,
                    completed_at TEXT,
                    properties_found INTEGER DEFAULT 0,
                    properties_new INTEGER DEFAULT 0,
                    properties_matching INTEGER DEFAULT 0,
                    errors TEXT DEFAULT '[]'
                )
            """)

            # Indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_properties_source
                ON properties(source)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_properties_first_seen
                ON properties(first_seen_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_properties_notified_instant
                ON properties(notified_instant)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_properties_notified_digest
                ON properties(notified_digest)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_properties_postcode
                ON properties(postcode)
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_properties_url
                ON properties(url) WHERE url != ''
            """)

            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def listing_exists(self, property_id: str) -> bool:
        """Check if a property already exists in the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM properties WHERE id = ?", (property_id,))
            return cursor.fetchone() is not None

    def add_property(self, prop: dict) -> bool:
        """Add a new property. Returns True if new, False if already existed."""
        property_id = prop.get("id", "")
        if not property_id:
            return False

        if self.listing_exists(property_id):
            # Update last_seen timestamp
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE properties SET last_seen_at = ? WHERE id = ?",
                    (_utcnow(), property_id),
                )
                conn.commit()
            return False

        features = prop.get("features", [])
        if isinstance(features, list):
            features = json.dumps(features)

        floorplan_urls = prop.get("floorplan_urls", [])
        if isinstance(floorplan_urls, list):
            floorplan_urls = json.dumps(floorplan_urls)

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO properties (
                    id, source, title, price, bedrooms, bathrooms,
                    property_type, area, address, postcode, url, image_url,
                    description, features, sqm, sqm_source, epc_rating,
                    lat, lon, tenure, floorplan_urls,
                    has_garden, has_balcony, has_parking, is_chain_free,
                    agent_name, agent_phone, nearest_station, walk_minutes
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
            """, (
                property_id,
                prop.get("source", ""),
                prop.get("title", ""),
                prop.get("price", 0),
                prop.get("bedrooms", 0),
                prop.get("bathrooms", 0),
                prop.get("property_type", ""),
                prop.get("area", ""),
                prop.get("address", ""),
                prop.get("postcode", ""),
                prop.get("url", ""),
                prop.get("image_url", ""),
                prop.get("description", ""),
                features,
                prop.get("sqm", 0),
                prop.get("sqm_source", ""),
                prop.get("epc_rating", ""),
                prop.get("lat", 0),
                prop.get("lon", 0),
                prop.get("tenure", ""),
                floorplan_urls,
                int(prop.get("has_garden", False)),
                int(prop.get("has_balcony", False)),
                int(prop.get("has_parking", False)),
                int(prop.get("is_chain_free", False)),
                prop.get("agent_name", ""),
                prop.get("agent_phone", ""),
                prop.get("nearest_station", ""),
                prop.get("walk_minutes", 0),
            ))
            conn.commit()
            logger.info(f"Added new property: {property_id} - {prop.get('title', '')}")
            return True

    def mark_notified_instant(self, property_id: str) -> None:
        """Mark a property as sent via instant notification."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE properties SET notified_instant = ? WHERE id = ?",
                (_utcnow(), property_id),
            )
            conn.commit()

    def mark_digest_sent(self, property_ids: list[str]) -> None:
        """Mark properties as included in a digest."""
        now = _utcnow()
        with self._get_connection() as conn:
            for pid in property_ids:
                conn.execute(
                    "UPDATE properties SET notified_digest = ? WHERE id = ?",
                    (now, pid),
                )
            conn.commit()
            logger.info(f"Marked {len(property_ids)} properties as digested")

    def update_enrichment(
        self,
        property_id: str,
        sqm: float = 0,
        sqm_source: str = "",
        nearest_station: str = "",
        walk_minutes: float = 0,
    ) -> None:
        """Update enrichment data for a property."""
        updates = []
        params = []
        if sqm > 0:
            updates.append("sqm = ?")
            params.append(sqm)
            updates.append("sqm_source = ?")
            params.append(sqm_source)
        if nearest_station:
            updates.append("nearest_station = ?")
            params.append(nearest_station)
            updates.append("walk_minutes = ?")
            params.append(walk_minutes)

        if not updates:
            return

        params.append(property_id)
        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE properties SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()

    def get_property(self, property_id: str) -> Optional[dict]:
        """Get a single property by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM properties WHERE id = ?", (property_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def get_recent_properties(self, hours: int = 24) -> list[dict]:
        """Get properties first seen within the specified time period."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM properties WHERE first_seen_at >= ? ORDER BY first_seen_at DESC",
                (cutoff,),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_undigested_properties(self) -> list[dict]:
        """Get properties that haven't been included in a digest yet."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM properties
                WHERE notified_digest IS NULL
                  AND is_active = TRUE
                ORDER BY first_seen_at DESC
            """)
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_hot_unnotified(self) -> list[dict]:
        """Get hot listings that haven't had instant notifications sent."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM properties
                WHERE notified_instant IS NULL
                  AND is_active = TRUE
                ORDER BY first_seen_at DESC
            """)
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def log_scrape_run(self, stats: dict) -> None:
        """Log a scrape run to the scrape_runs table."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO scrape_runs (started_at, completed_at, properties_found,
                    properties_new, properties_matching, errors)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                stats.get("started_at", ""),
                stats.get("completed_at", _utcnow()),
                stats.get("properties_found", 0),
                stats.get("properties_new", 0),
                stats.get("properties_matching", 0),
                json.dumps(stats.get("errors", [])),
            ))
            conn.commit()

    def cleanup_old_properties(self, days: int = 90) -> int:
        """Delete properties older than N days. Returns count deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM properties WHERE first_seen_at < ?", (cutoff,)
            )
            count = cursor.rowcount
            conn.commit()
            if count > 0:
                logger.info(f"Cleaned up {count} properties older than {days} days")
            return count

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            def count(query, params=()):
                cursor.execute(query, params)
                return cursor.fetchone()[0]

            total_all = count("SELECT COUNT(*) FROM properties")
            total_24h = count(
                "SELECT COUNT(*) FROM properties WHERE first_seen_at >= ?",
                (cutoff_24h,),
            )
            total_7d = count(
                "SELECT COUNT(*) FROM properties WHERE first_seen_at >= ?",
                (cutoff_7d,),
            )
            notified_instant = count(
                "SELECT COUNT(*) FROM properties WHERE notified_instant IS NOT NULL"
            )
            notified_digest = count(
                "SELECT COUNT(*) FROM properties WHERE notified_digest IS NOT NULL"
            )
            active = count(
                "SELECT COUNT(*) FROM properties WHERE is_active = TRUE"
            )

            # Per-source counts
            cursor.execute(
                "SELECT source, COUNT(*) as cnt FROM properties GROUP BY source"
            )
            by_source = {row["source"]: row["cnt"] for row in cursor.fetchall()}

            # Price stats
            cursor.execute(
                "SELECT MIN(price) as min_p, MAX(price) as max_p, AVG(price) as avg_p "
                "FROM properties WHERE price > 0"
            )
            price_row = cursor.fetchone()

            return {
                "total": {"all_time": total_all, "last_24h": total_24h, "last_7d": total_7d},
                "notified_instant": notified_instant,
                "notified_digest": notified_digest,
                "active": active,
                "by_source": by_source,
                "price": {
                    "min": price_row["min_p"] if price_row["min_p"] else 0,
                    "max": price_row["max_p"] if price_row["max_p"] else 0,
                    "avg": round(price_row["avg_p"]) if price_row["avg_p"] else 0,
                },
            }

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a dictionary with parsed JSON fields."""
        data = dict(row)
        for json_field in ("features", "floorplan_urls"):
            if data.get(json_field):
                try:
                    data[json_field] = json.loads(data[json_field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return data
