import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

_DATABASE_URL = os.getenv("DATABASE_URL", "")


@contextmanager
def get_db():
    url = _DATABASE_URL.replace("postgres://", "postgresql://", 1)
    conn = psycopg2.connect(url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def init_db() -> None:
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phrases (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT  NOT NULL,
                phrase      TEXT    NOT NULL,
                translation TEXT    NOT NULL,
                example     TEXT,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS srs_data (
                phrase_id   INTEGER PRIMARY KEY REFERENCES phrases(id) ON DELETE CASCADE,
                ease_factor REAL    DEFAULT 2.5,
                interval    INTEGER DEFAULT 1,
                repetitions INTEGER DEFAULT 0,
                next_review TIMESTAMPTZ DEFAULT NOW(),
                last_review TIMESTAMPTZ
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id           SERIAL PRIMARY KEY,
                user_id      BIGINT NOT NULL,
                pattern_name TEXT   NOT NULL,
                structure    TEXT,
                note         TEXT,
                examples     TEXT,
                level        TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)


def add_phrase(user_id: int, phrase: str, translation: str, example: str | None) -> int:
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute(
            "INSERT INTO phrases (user_id, phrase, translation, example) VALUES (%s, %s, %s, %s) RETURNING id",
            (user_id, phrase, translation, example),
        )
        phrase_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO srs_data (phrase_id) VALUES (%s)", (phrase_id,))
        return phrase_id


def get_due_phrases(user_id: int) -> list:
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute(
            """
            SELECT p.id, p.phrase, p.translation, p.example,
                   s.ease_factor, s.interval, s.repetitions
            FROM phrases p
            JOIN srs_data s ON p.id = s.phrase_id
            WHERE p.user_id = %s AND s.next_review <= %s
            ORDER BY s.next_review ASC
            """,
            (user_id, _now_utc()),
        )
        return cur.fetchall()


def update_srs(phrase_id: int, ease_factor: float, interval: int, repetitions: int) -> None:
    next_review = _now_utc() + timedelta(days=interval)
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute(
            """
            UPDATE srs_data
            SET ease_factor=%s, interval=%s, repetitions=%s, next_review=%s, last_review=%s
            WHERE phrase_id=%s
            """,
            (ease_factor, interval, repetitions, next_review, _now_utc(), phrase_id),
        )


def get_all_phrases(user_id: int, offset: int = 0, limit: int = 5) -> list:
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute(
            """
            SELECT p.id, p.phrase, p.translation, s.repetitions, s.next_review
            FROM phrases p
            JOIN srs_data s ON p.id = s.phrase_id
            WHERE p.user_id = %s
            ORDER BY p.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, limit, offset),
        )
        return cur.fetchall()


def count_phrases(user_id: int) -> int:
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT COUNT(*) AS cnt FROM phrases WHERE user_id = %s", (user_id,))
        return cur.fetchone()["cnt"]


def get_patterns(user_id: int) -> list:
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute(
            """
            SELECT id, pattern_name, structure, note, examples, level
            FROM patterns WHERE user_id = %s ORDER BY created_at DESC
            """,
            (user_id,),
        )
        return cur.fetchall()


def count_patterns(user_id: int) -> int:
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT COUNT(*) AS cnt FROM patterns WHERE user_id = %s", (user_id,))
        return cur.fetchone()["cnt"]


def add_pattern(user_id: int, pattern_name: str, structure: str, note: str, examples: str, level: str) -> int:
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute(
            """
            INSERT INTO patterns (user_id, pattern_name, structure, note, examples, level)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (user_id, pattern_name, structure, note, examples, level),
        )
        return cur.fetchone()["id"]


def delete_phrase(phrase_id: int, user_id: int) -> bool:
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute(
            "DELETE FROM phrases WHERE id = %s AND user_id = %s", (phrase_id, user_id)
        )
        return cur.rowcount > 0


def get_stats(user_id: int) -> dict:
    now = _now_utc()
    with get_db() as conn:
        cur = _cur(conn)
        cur.execute("SELECT COUNT(*) AS cnt FROM phrases WHERE user_id = %s", (user_id,))
        total = cur.fetchone()["cnt"]

        cur.execute(
            """
            SELECT COUNT(*) AS cnt FROM phrases p
            JOIN srs_data s ON p.id = s.phrase_id
            WHERE p.user_id = %s AND s.next_review <= %s
            """,
            (user_id, now),
        )
        due = cur.fetchone()["cnt"]

        cur.execute(
            """
            SELECT COUNT(*) AS cnt FROM phrases p
            JOIN srs_data s ON p.id = s.phrase_id
            WHERE p.user_id = %s AND s.repetitions >= 3
            """,
            (user_id,),
        )
        learned = cur.fetchone()["cnt"]

    return {"total": total, "due": due, "learned": learned}
