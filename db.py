import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

_data_dir = os.getenv("DATA_DIR", str(Path(__file__).parent))
DB_PATH = Path(_data_dir) / "englishbot.db"


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS phrases (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                phrase      TEXT    NOT NULL,
                translation TEXT    NOT NULL,
                example     TEXT,
                created_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS srs_data (
                phrase_id   INTEGER PRIMARY KEY REFERENCES phrases(id) ON DELETE CASCADE,
                ease_factor REAL    DEFAULT 2.5,
                interval    INTEGER DEFAULT 1,
                repetitions INTEGER DEFAULT 0,
                next_review TEXT    DEFAULT (datetime('now')),
                last_review TEXT
            );

            CREATE TABLE IF NOT EXISTS patterns (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                pattern_name TEXT    NOT NULL,
                structure    TEXT,
                note         TEXT,
                examples     TEXT,
                level        TEXT,
                created_at   TEXT    DEFAULT (datetime('now'))
            );
        """)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def add_phrase(user_id: int, phrase: str, translation: str, example: str | None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO phrases (user_id, phrase, translation, example) VALUES (?, ?, ?, ?)",
            (user_id, phrase, translation, example),
        )
        phrase_id = cur.lastrowid
        conn.execute("INSERT INTO srs_data (phrase_id) VALUES (?)", (phrase_id,))
        return phrase_id


def get_due_phrases(user_id: int) -> list[sqlite3.Row]:
    now = _now_utc()
    with get_db() as conn:
        return conn.execute(
            """
            SELECT p.id, p.phrase, p.translation, p.example,
                   s.ease_factor, s.interval, s.repetitions
            FROM phrases p
            JOIN srs_data s ON p.id = s.phrase_id
            WHERE p.user_id = ? AND s.next_review <= ?
            ORDER BY s.next_review ASC
            """,
            (user_id, now),
        ).fetchall()


def update_srs(phrase_id: int, ease_factor: float, interval: int, repetitions: int) -> None:
    next_review = (datetime.now(timezone.utc) + timedelta(days=interval)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute(
            """
            UPDATE srs_data
            SET ease_factor=?, interval=?, repetitions=?, next_review=?, last_review=?
            WHERE phrase_id=?
            """,
            (ease_factor, interval, repetitions, next_review, _now_utc(), phrase_id),
        )


def get_all_phrases(user_id: int, offset: int = 0, limit: int = 5) -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            """
            SELECT p.id, p.phrase, p.translation, s.repetitions, s.next_review
            FROM phrases p
            JOIN srs_data s ON p.id = s.phrase_id
            WHERE p.user_id = ?
            ORDER BY p.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset),
        ).fetchall()


def count_phrases(user_id: int) -> int:
    with get_db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM phrases WHERE user_id = ?", (user_id,)
        ).fetchone()[0]


def add_pattern(user_id: int, pattern_name: str, structure: str, note: str, examples: str, level: str) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO patterns (user_id, pattern_name, structure, note, examples, level) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, pattern_name, structure, note, examples, level),
        )
        return cur.lastrowid


def delete_phrase(phrase_id: int, user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM phrases WHERE id = ? AND user_id = ?", (phrase_id, user_id)
        )
        return cur.rowcount > 0


def get_stats(user_id: int) -> dict:
    now = _now_utc()
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM phrases WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        due = conn.execute(
            """
            SELECT COUNT(*) FROM phrases p
            JOIN srs_data s ON p.id = s.phrase_id
            WHERE p.user_id = ? AND s.next_review <= ?
            """,
            (user_id, now),
        ).fetchone()[0]
        learned = conn.execute(
            """
            SELECT COUNT(*) FROM phrases p
            JOIN srs_data s ON p.id = s.phrase_id
            WHERE p.user_id = ? AND s.repetitions >= 3
            """,
            (user_id,),
        ).fetchone()[0]
    return {"total": total, "due": due, "learned": learned}
