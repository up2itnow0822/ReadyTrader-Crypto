import json
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from storage_paths import data_path, ensure_parent


@dataclass
class StrategyArtifact:
    """Represents a registered trading strategy."""

    strategy_id: str
    name: str
    author: str
    backtest_pnl_pct: float
    backtest_sharpe: float
    logic_summary: str
    config_json: str
    created_at: int
    # Extended fields for marketplace
    version: str = "1.0.0"
    category: str = "general"
    tags: str = ""
    downloads: int = 0
    rating: float = 0.0
    rating_count: int = 0
    status: str = "active"  # active, deprecated, under_review
    strategy_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "author": self.author,
            "backtest_pnl_pct": self.backtest_pnl_pct,
            "backtest_sharpe": self.backtest_sharpe,
            "logic_summary": self.logic_summary,
            "config": json.loads(self.config_json) if self.config_json else {},
            "created_at": self.created_at,
            "version": self.version,
            "category": self.category,
            "tags": self.tags.split(",") if self.tags else [],
            "downloads": self.downloads,
            "rating": self.rating,
            "rating_count": self.rating_count,
            "status": self.status,
        }


@dataclass
class StrategyReview:
    """User review of a strategy."""

    review_id: str
    strategy_id: str
    author: str
    rating: float
    comment: str
    created_at: int


class StrategyRegistry:
    """
    Enhanced marketplace for saving, sharing, and discovering agent strategies.

    Features:
    - Strategy versioning
    - Categories and tags
    - Ratings and reviews
    - Download tracking
    - Search and filtering
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("READYTRADER_STRATEGY_DB_PATH", os.getenv("STRATEGY_DB_PATH", data_path("strategies.db")))
        ensure_parent(self.db_path)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Main strategies table with extended fields
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategies (
                    strategy_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    author TEXT NOT NULL,
                    backtest_pnl_pct REAL,
                    backtest_sharpe REAL,
                    logic_summary TEXT,
                    config_json TEXT,
                    created_at INTEGER NOT NULL,
                    version TEXT DEFAULT '1.0.0',
                    category TEXT DEFAULT 'general',
                    tags TEXT DEFAULT '',
                    downloads INTEGER DEFAULT 0,
                    rating REAL DEFAULT 0.0,
                    rating_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    strategy_code TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_name ON strategies(name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_category ON strategies(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_author ON strategies(author)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_rating ON strategies(rating)")

            # Reviews table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_reviews (
                    review_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    rating REAL NOT NULL,
                    comment TEXT,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_strategy ON strategy_reviews(strategy_id)")

            # Version history table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_versions (
                    version_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    config_json TEXT,
                    strategy_code TEXT,
                    created_at INTEGER NOT NULL,
                    changelog TEXT,
                    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
                )
            """)

            # Schema migration for older databases
            cols = {row[1] for row in conn.execute("PRAGMA table_info(strategies)").fetchall()}
            if "version" not in cols:
                conn.execute("ALTER TABLE strategies ADD COLUMN version TEXT DEFAULT '1.0.0'")
            if "category" not in cols:
                conn.execute("ALTER TABLE strategies ADD COLUMN category TEXT DEFAULT 'general'")
            if "tags" not in cols:
                conn.execute("ALTER TABLE strategies ADD COLUMN tags TEXT DEFAULT ''")
            if "downloads" not in cols:
                conn.execute("ALTER TABLE strategies ADD COLUMN downloads INTEGER DEFAULT 0")
            if "rating" not in cols:
                conn.execute("ALTER TABLE strategies ADD COLUMN rating REAL DEFAULT 0.0")
            if "rating_count" not in cols:
                conn.execute("ALTER TABLE strategies ADD COLUMN rating_count INTEGER DEFAULT 0")
            if "status" not in cols:
                conn.execute("ALTER TABLE strategies ADD COLUMN status TEXT DEFAULT 'active'")
            if "strategy_code" not in cols:
                conn.execute("ALTER TABLE strategies ADD COLUMN strategy_code TEXT DEFAULT ''")

            conn.commit()

    def register_strategy(
        self,
        name: str,
        author: str,
        pnl: float,
        sharpe: float,
        summary: str,
        config: Dict[str, Any],
        strategy_code: str = "",
        category: str = "general",
        tags: List[str] = None,
        version: str = "1.0.0",
    ) -> StrategyArtifact:
        """
        Register a new strategy in the marketplace.
        """
        strategy_id = secrets.token_hex(6)
        tags_str = ",".join(tags) if tags else ""

        artifact = StrategyArtifact(
            strategy_id=strategy_id,
            name=name,
            author=author,
            backtest_pnl_pct=float(pnl),
            backtest_sharpe=float(sharpe),
            logic_summary=summary,
            config_json=json.dumps(config),
            created_at=int(time.time()),
            version=version,
            category=category,
            tags=tags_str,
            strategy_code=strategy_code,
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO strategies (
                    strategy_id, name, author, backtest_pnl_pct, backtest_sharpe,
                    logic_summary, config_json, created_at, version, category,
                    tags, strategy_code
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    artifact.strategy_id,
                    artifact.name,
                    artifact.author,
                    artifact.backtest_pnl_pct,
                    artifact.backtest_sharpe,
                    artifact.logic_summary,
                    artifact.config_json,
                    artifact.created_at,
                    artifact.version,
                    artifact.category,
                    artifact.tags,
                    artifact.strategy_code,
                ),
            )
        return artifact

    def update_strategy(
        self,
        strategy_id: str,
        config: Dict[str, Any] = None,
        strategy_code: str = None,
        version: str = None,
        changelog: str = "",
    ) -> Optional[StrategyArtifact]:
        """
        Update a strategy and create a version history entry.
        """
        existing = self.get_strategy(strategy_id)
        if not existing:
            return None

        with sqlite3.connect(self.db_path) as conn:
            # Save current version to history
            version_id = secrets.token_hex(6)
            conn.execute(
                """
                INSERT INTO strategy_versions (
                    version_id, strategy_id, version, config_json,
                    strategy_code, created_at, changelog
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    version_id,
                    strategy_id,
                    existing.version,
                    existing.config_json,
                    existing.strategy_code,
                    int(time.time()),
                    changelog,
                ),
            )

            # Update the strategy
            updates = []
            params = []

            if config is not None:
                updates.append("config_json = ?")
                params.append(json.dumps(config))

            if strategy_code is not None:
                updates.append("strategy_code = ?")
                params.append(strategy_code)

            if version is not None:
                updates.append("version = ?")
                params.append(version)

            if updates:
                params.append(strategy_id)
                conn.execute(f"UPDATE strategies SET {', '.join(updates)} WHERE strategy_id = ?", params)

        return self.get_strategy(strategy_id)

    def list_strategies(
        self,
        limit: int = 10,
        offset: int = 0,
        category: str = None,
        author: str = None,
        sort_by: str = "rating",  # rating, downloads, pnl, sharpe, created_at
        sort_order: str = "desc",
        search: str = None,
        status: str = "active",
    ) -> List[StrategyArtifact]:
        """
        List strategies with filtering and sorting.
        """
        query = "SELECT * FROM strategies WHERE status = ?"
        params: List[Any] = [status]

        if category:
            query += " AND category = ?"
            params.append(category)

        if author:
            query += " AND author = ?"
            params.append(author)

        if search:
            query += " AND (name LIKE ? OR logic_summary LIKE ? OR tags LIKE ?)"
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])

        # Validate sort column
        valid_sorts = {
            "rating": "rating",
            "downloads": "downloads",
            "pnl": "backtest_pnl_pct",
            "sharpe": "backtest_sharpe",
            "created_at": "created_at",
            "name": "name",
        }
        sort_col = valid_sorts.get(sort_by, "rating")
        sort_dir = "DESC" if sort_order.lower() == "desc" else "ASC"

        query += f" ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        results = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            for row in cursor:
                results.append(self._row_to_artifact(row))
        return results

    def get_strategy(self, strategy_id: str) -> Optional[StrategyArtifact]:
        """Get a single strategy by ID."""
        query = "SELECT * FROM strategies WHERE strategy_id = ?"
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(query, (strategy_id,)).fetchone()
            if row:
                return self._row_to_artifact(row)
        return None

    def download_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """
        Download a strategy (increments download counter).
        Returns the full strategy including code.
        """
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE strategies SET downloads = downloads + 1 WHERE strategy_id = ?", (strategy_id,))

        result = strategy.to_dict()
        result["strategy_code"] = strategy.strategy_code
        return result

    def add_review(
        self,
        strategy_id: str,
        author: str,
        rating: float,
        comment: str = "",
    ) -> Optional[StrategyReview]:
        """
        Add a review for a strategy.
        Updates the strategy's average rating.
        """
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return None

        rating = max(0.0, min(5.0, float(rating)))  # Clamp to 0-5
        review_id = secrets.token_hex(6)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO strategy_reviews (
                    review_id, strategy_id, author, rating, comment, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (review_id, strategy_id, author, rating, comment, int(time.time())),
            )

            # Update average rating
            cursor = conn.execute("SELECT AVG(rating), COUNT(*) FROM strategy_reviews WHERE strategy_id = ?", (strategy_id,))
            row = cursor.fetchone()
            avg_rating = row[0] or 0.0
            count = row[1] or 0

            conn.execute("UPDATE strategies SET rating = ?, rating_count = ? WHERE strategy_id = ?", (avg_rating, count, strategy_id))

        return StrategyReview(review_id=review_id, strategy_id=strategy_id, author=author, rating=rating, comment=comment, created_at=int(time.time()))

    def get_reviews(self, strategy_id: str, limit: int = 20) -> List[StrategyReview]:
        """Get reviews for a strategy."""
        results = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT review_id, strategy_id, author, rating, comment, created_at
                FROM strategy_reviews
                WHERE strategy_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (strategy_id, limit),
            )
            for row in cursor:
                results.append(StrategyReview(*row))
        return results

    def get_categories(self) -> List[Dict[str, Any]]:
        """Get all categories with strategy counts."""
        results = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT category, COUNT(*) as count
                FROM strategies
                WHERE status = 'active'
                GROUP BY category
                ORDER BY count DESC
                """
            )
            for row in cursor:
                results.append({"category": row[0], "count": row[1]})
        return results

    def get_popular_tags(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get most popular tags."""
        tag_counts: Dict[str, int] = {}

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT tags FROM strategies WHERE status = 'active' AND tags != ''")
            for row in cursor:
                tags = row[0].split(",") if row[0] else []
                for tag in tags:
                    tag = tag.strip()
                    if tag:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        return [{"tag": t, "count": c} for t, c in sorted_tags[:limit]]

    def _row_to_artifact(self, row) -> StrategyArtifact:
        """Convert a database row to a StrategyArtifact."""
        return StrategyArtifact(
            strategy_id=row[0],
            name=row[1],
            author=row[2],
            backtest_pnl_pct=row[3],
            backtest_sharpe=row[4],
            logic_summary=row[5],
            config_json=row[6],
            created_at=row[7],
            version=row[8] if len(row) > 8 else "1.0.0",
            category=row[9] if len(row) > 9 else "general",
            tags=row[10] if len(row) > 10 else "",
            downloads=row[11] if len(row) > 11 else 0,
            rating=row[12] if len(row) > 12 else 0.0,
            rating_count=row[13] if len(row) > 13 else 0,
            status=row[14] if len(row) > 14 else "active",
            strategy_code=row[15] if len(row) > 15 else "",
        )
