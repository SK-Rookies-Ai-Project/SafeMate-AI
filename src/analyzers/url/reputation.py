"""Local URL reputation lookup backed by url_binary_dataset.csv.

This is not an external reputation service. It is an exact-match index over the
project's labeled raw URL dataset, using the same canonical URL text as TF-IDF.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from src.analyzers.url.constants import BENIGN_LABELS, URL_BINARY_CSV, URL_REPUTATION_DB
from src.analyzers.url.features import canonicalize_url_for_tfidf


SCHEMA = """
CREATE TABLE IF NOT EXISTS url_reputation (
    canonical_url TEXT PRIMARY KEY,
    benign_count INTEGER NOT NULL DEFAULT 0,
    risk_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_url_reputation_counts
ON url_reputation(risk_count, benign_count);
"""


def _is_benign(label: object) -> bool:
    return str(label).strip() in BENIGN_LABELS


def _connect(path: Union[str, Path]) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path))
    conn.executescript(SCHEMA)
    return conn


def build_url_reputation_db(
    csv_path: Union[str, Path] = URL_BINARY_CSV,
    db_path: Union[str, Path] = URL_REPUTATION_DB,
    chunksize: int = 200_000,
    nrows: Optional[int] = None,
) -> Path:
    """Build an exact canonical URL -> label-count SQLite index."""
    csv_path = Path(csv_path)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = _connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        reader = pd.read_csv(
            csv_path,
            usecols=[0, 1],
            chunksize=chunksize,
            nrows=nrows,
        )
        for chunk in reader:
            counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            for raw_url, label in zip(chunk.iloc[:, 0], chunk.iloc[:, 1]):
                canonical = canonicalize_url_for_tfidf(str(raw_url))
                if not canonical:
                    continue
                if _is_benign(label):
                    counts[canonical][0] += 1
                else:
                    counts[canonical][1] += 1

            conn.executemany(
                """
                INSERT INTO url_reputation(canonical_url, benign_count, risk_count)
                VALUES (?, ?, ?)
                ON CONFLICT(canonical_url) DO UPDATE SET
                    benign_count = benign_count + excluded.benign_count,
                    risk_count = risk_count + excluded.risk_count
                """,
                ((url, values[0], values[1]) for url, values in counts.items()),
            )
            conn.commit()
    finally:
        conn.close()
    return db_path


def lookup_url_reputation(
    url: str,
    db_path: Union[str, Path] = URL_REPUTATION_DB,
) -> Optional[dict]:
    """Return exact-match local reputation stats, or None when unavailable."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None

    canonical = canonicalize_url_for_tfidf(url)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT benign_count, risk_count
            FROM url_reputation
            WHERE canonical_url = ?
            """,
            (canonical,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    benign_count, risk_count = int(row[0]), int(row[1])
    total = benign_count + risk_count
    if total <= 0:
        return None
    risk_score = risk_count / total
    return {
        "canonical_url": canonical,
        "benign_count": benign_count,
        "risk_count": risk_count,
        "total_count": total,
        "label": "정상" if benign_count >= risk_count else "악성",
        "risk_score": risk_score,
    }
