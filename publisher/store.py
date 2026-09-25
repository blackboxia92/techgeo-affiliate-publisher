from __future__ import annotations

import sqlite3
from pathlib import Path


class StateStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS pages (
                slug TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                public_url TEXT NOT NULL,
                output_path TEXT NOT NULL,
                status TEXT NOT NULL,
                lastmod TEXT NOT NULL,
                pending_indexnow INTEGER NOT NULL DEFAULT 0,
                UNIQUE(content_hash)
            );
            CREATE TABLE IF NOT EXISTS indexnow_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                url_count INTEGER NOT NULL,
                http_status INTEGER NOT NULL,
                response_body TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def upsert_page(
        self,
        *,
        slug: str,
        content_hash: str,
        public_url: str,
        output_path: str,
        status: str,
        lastmod: str,
    ) -> bool:
        existing = self.connection.execute(
            "SELECT content_hash, public_url, status FROM pages WHERE slug = ?", (slug,)
        ).fetchone()
        changed = (
            existing is None
            or existing["content_hash"] != content_hash
            or existing["public_url"] != public_url
            or existing["status"] != status
        )
        pending = 1 if changed and status == "reviewed" else 0
        try:
            self.connection.execute(
                """
                INSERT INTO pages(slug, content_hash, public_url, output_path, status, lastmod, pending_indexnow)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    public_url = excluded.public_url,
                    output_path = excluded.output_path,
                    status = excluded.status,
                    lastmod = excluded.lastmod,
                    pending_indexnow = CASE
                        WHEN excluded.pending_indexnow = 1 THEN 1
                        ELSE pages.pending_indexnow
                    END
                """,
                (slug, content_hash, public_url, output_path, status, lastmod, pending),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"Duplicate page body detected for {slug!r}; each page must add unique value."
            ) from exc
        self.connection.commit()
        return changed

    def indexable_pages(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM pages WHERE status = 'reviewed' ORDER BY lastmod DESC, slug"
            )
        )

    def prune_except(self, slugs: set[str]) -> None:
        if not slugs:
            self.connection.execute("DELETE FROM pages")
        else:
            placeholders = ",".join("?" for _ in slugs)
            self.connection.execute(
                f"DELETE FROM pages WHERE slug NOT IN ({placeholders})", tuple(sorted(slugs))
            )
        self.connection.commit()

    def pending_urls(self) -> list[str]:
        return [
            row["public_url"]
            for row in self.connection.execute(
                "SELECT public_url FROM pages WHERE pending_indexnow = 1 ORDER BY slug"
            )
        ]

    def mark_submitted(self, urls: list[str], status: int, body: str) -> None:
        self.connection.executemany(
            "UPDATE pages SET pending_indexnow = 0 WHERE public_url = ?",
            ((url,) for url in urls),
        )
        self.connection.execute(
            "INSERT INTO indexnow_submissions(url_count, http_status, response_body) VALUES (?, ?, ?)",
            (len(urls), status, body[:2000]),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
