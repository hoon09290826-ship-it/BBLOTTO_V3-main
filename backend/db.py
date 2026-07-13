import sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "database"
DB_PATH = DB_DIR / "bblotto_v34.db"


def conn():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            grade TEXT DEFAULT '일반',
            memo TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER,
            member_name TEXT DEFAULT '',
            round_no INTEGER,
            mode TEXT,
            count INTEGER,
            numbers TEXT,
            analysis TEXT,
            sms TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(member_id) REFERENCES members(id)
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS sms_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER,
            member_name TEXT DEFAULT '',
            round_no INTEGER,
            body TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS winning_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER,
            member_name TEXT DEFAULT '',
            round_no INTEGER,
            target_numbers TEXT,
            win_numbers TEXT,
            bonus INTEGER,
            match_count INTEGER,
            bonus_match INTEGER,
            rank TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS consultations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER,
            member_name TEXT DEFAULT '',
            contact_type TEXT DEFAULT '전화',
            status TEXT DEFAULT '상담완료',
            memo TEXT DEFAULT '',
            next_action TEXT DEFAULT '',
            next_date TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(member_id) REFERENCES members(id)
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_consultations_member ON consultations(member_id, id DESC)")

        c.execute("""
        CREATE TABLE IF NOT EXISTS draws (
            round_no INTEGER PRIMARY KEY,
            draw_date TEXT DEFAULT '',
            n1 INTEGER NOT NULL,
            n2 INTEGER NOT NULL,
            n3 INTEGER NOT NULL,
            n4 INTEGER NOT NULL,
            n5 INTEGER NOT NULL,
            n6 INTEGER NOT NULL,
            bonus INTEGER NOT NULL,
            source TEXT DEFAULT 'manual',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_draws_round ON draws(round_no DESC)")

        c.execute("""
        CREATE TABLE IF NOT EXISTS sms_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            greeting TEXT DEFAULT '',
            footer TEXT DEFAULT '',
            memo TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sms_templates_id ON sms_templates(id DESC)")
        # 기본 문자 템플릿은 없을 때만 자동 생성
        exists = c.execute("SELECT COUNT(*) AS c FROM sms_templates").fetchone()["c"]
        if exists == 0:
            c.execute("INSERT INTO sms_templates(name,greeting,footer,memo) VALUES(?,?,?,?)", (
                "기본 추천번호 안내",
                "안녕하세요 {회원명}님, BBLOTTO입니다.\n이번 회차 추천번호 전달드립니다.",
                "좋은 결과 있으시길 바랍니다.",
                "V14 기본 템플릿"
            ))
        c.commit()


def rows_to_dicts(rows):
    return [dict(r) for r in rows]
