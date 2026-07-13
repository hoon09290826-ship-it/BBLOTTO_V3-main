
import json
import urllib.request
from typing import List, Dict, Optional
from .db import conn
from .data import DRAWS as SEED_DRAWS


def _row_to_draw(row) -> Dict:
    return {
        "r": row["round_no"],
        "d": row["draw_date"] or "",
        "n": [row["n1"], row["n2"], row["n3"], row["n4"], row["n5"], row["n6"]],
        "b": row["bonus"],
        "source": row["source"] or "manual",
    }


def validate_numbers(numbers: List[int], bonus: int) -> List[int]:
    nums = sorted(set(int(n) for n in numbers if 1 <= int(n) <= 45))
    if len(nums) != 6:
        raise ValueError("당첨번호 6개를 정확히 입력해주세요.")
    bonus = int(bonus)
    if bonus < 1 or bonus > 45:
        raise ValueError("보너스 번호는 1~45 사이여야 합니다.")
    if bonus in nums:
        raise ValueError("보너스 번호는 당첨번호 6개와 중복될 수 없습니다.")
    return nums


def seed_draws_if_empty():
    with conn() as c:
        count = c.execute("SELECT COUNT(*) AS c FROM draws").fetchone()["c"]
        if count:
            return
        for d in SEED_DRAWS:
            nums = d["n"]
            c.execute("""INSERT OR REPLACE INTO draws(round_no, draw_date, n1,n2,n3,n4,n5,n6, bonus, source)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""", (d["r"], d.get("d", ""), *nums, d["b"], "seed"))


def get_draws(limit: Optional[int] = None) -> List[Dict]:
    seed_draws_if_empty()
    q = "SELECT * FROM draws ORDER BY round_no DESC"
    params = ()
    if limit:
        q += " LIMIT ?"; params = (int(limit),)
    with conn() as c:
        rows = c.execute(q, params).fetchall()
    return [_row_to_draw(r) for r in rows]


def get_draw(round_no: int) -> Optional[Dict]:
    seed_draws_if_empty()
    with conn() as c:
        row = c.execute("SELECT * FROM draws WHERE round_no=?", (int(round_no),)).fetchone()
    return _row_to_draw(row) if row else None


def save_draw(round_no: int, draw_date: str, numbers: List[int], bonus: int, source: str = "manual") -> Dict:
    nums = validate_numbers(numbers, bonus)
    with conn() as c:
        c.execute("""INSERT INTO draws(round_no, draw_date, n1,n2,n3,n4,n5,n6, bonus, source, updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                     ON CONFLICT(round_no) DO UPDATE SET
                     draw_date=excluded.draw_date,n1=excluded.n1,n2=excluded.n2,n3=excluded.n3,n4=excluded.n4,n5=excluded.n5,n6=excluded.n6,
                     bonus=excluded.bonus,source=excluded.source,updated_at=CURRENT_TIMESTAMP""", (int(round_no), draw_date, *nums, int(bonus), source))
    return get_draw(round_no)


def delete_draw(round_no: int):
    with conn() as c:
        c.execute("DELETE FROM draws WHERE round_no=?", (int(round_no),))


def fetch_dhlottery(round_no: int) -> Dict:
    url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={int(round_no)}"
    with urllib.request.urlopen(url, timeout=8) as res:
        data = json.loads(res.read().decode("utf-8"))
    if data.get("returnValue") != "success":
        raise RuntimeError("해당 회차 조회 결과가 없습니다.")
    nums = [int(data[f"drwtNo{i}"]) for i in range(1, 7)]
    return {
        "r": int(data["drwNo"]),
        "d": str(data.get("drwNoDate") or ""),
        "n": nums,
        "b": int(data["bnusNo"]),
        "source": "dhlottery",
    }
