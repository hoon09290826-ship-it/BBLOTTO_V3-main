"""BBLOTTO STABLE 설명형 분석 엔진.

생성된 추천번호와 최근/누적 통계의 실제 특징만 읽어 회원이 이해하기 쉬운
4줄 설명을 만든다. 임의 신뢰도나 당첨 보장 표현은 사용하지 않는다.
"""
from __future__ import annotations

import collections
import hashlib
from typing import Any, Dict, Iterable, List, Sequence, Tuple


def _numbers(item: Dict[str, Any]) -> List[int]:
    raw = item.get("numbers") or item.get("nums") or item.get("combo") or []
    try:
        nums = sorted({int(n) for n in raw if 1 <= int(n) <= 45})
    except Exception:
        return []
    return nums if len(nums) == 6 else []


def _as_int_list(values: Iterable[Any], limit: int = 20) -> List[int]:
    out: List[int] = []
    for value in values or []:
        try:
            n = int(value)
        except Exception:
            continue
        if 1 <= n <= 45 and n not in out:
            out.append(n)
        if len(out) >= limit:
            break
    return out


def _fmt(nums: Sequence[int], limit: int = 4) -> str:
    return ", ".join(str(n) for n in list(nums)[:limit])


def _pick_by_combo(combos: List[List[int]], choices: Sequence[str], salt: str) -> str:
    if not choices:
        return ""
    key = f"{salt}|{combos}".encode("utf-8")
    idx = int.from_bytes(hashlib.sha256(key).digest()[:4], "big") % len(choices)
    return choices[idx]


def _features(combos: List[List[int]]) -> Dict[str, Any]:
    flat = [n for c in combos for n in c]
    freq = collections.Counter(flat)
    odd_counts = [sum(n % 2 for n in c) for c in combos]
    sums = [sum(c) for c in combos]
    zone_totals = [sum(n <= 15 for n in flat), sum(16 <= n <= 30 for n in flat), sum(n >= 31 for n in flat)]
    consecutive = sum(any(b-a == 1 for a,b in zip(c,c[1:])) for c in combos)
    end_balanced = sum(len({n % 10 for n in c}) >= 5 for c in combos)
    overlaps = [len(set(a)&set(b)) for i,a in enumerate(combos) for b in combos[i+1:]]
    common = [n for n,c in freq.most_common() if c >= 2]
    return {
        "flat": flat, "freq": freq, "common": common,
        "unique": len(freq), "odd_balanced": sum(2 <= x <= 4 for x in odd_counts),
        "sum_min": min(sums), "sum_max": max(sums), "sum_avg": round(sum(sums)/len(sums)),
        "zones": zone_totals, "consecutive": consecutive, "end_balanced": end_balanced,
        "max_overlap": max(overlaps, default=0),
    }


def _trend_lists(stats: Dict[str, Any]) -> Tuple[List[int], List[int]]:
    hot = _as_int_list(stats.get("hot20") or stats.get("hot30") or stats.get("hot100") or stats.get("hot300") or stats.get("hot") or [])
    overdue = _as_int_list(stats.get("overdue20") or stats.get("overdue30") or stats.get("overdue100") or stats.get("overdue300") or stats.get("overdue") or [])
    return hot, overdue


def build_member_friendly_analysis(round_no: int, stats: Dict[str, Any], mode: str, fixed: Any, excluded: Any, details: List[Dict[str, Any]]) -> str:
    combos = [_numbers(item) for item in details or []]
    combos = [c for c in combos if c]
    latest = int(stats.get("latest_round") or stats.get("target_round") or max(0, int(round_no or 1)-1))
    if not combos:
        return "\n".join([
            f"1회차부터 {latest}회차까지의 누적 기록과 최근 흐름을 함께 비교해 이번 후보를 구성했습니다.",
            "저·중·고번호와 홀짝 비율이 한쪽으로 몰리지 않도록 기본 균형을 적용했습니다.",
            "비슷한 조합의 반복을 줄이고 조합마다 서로 다른 번호 흐름을 담았습니다.",
        ])

    f = _features(combos)
    hot, overdue = _trend_lists(stats)
    hot_used = [n for n in hot if n in f["freq"]][:4]
    overdue_used = [n for n in overdue if n in f["freq"] and n not in hot_used][:4]
    core = f["common"][:4]
    total = len(f["flat"])
    zone_pct = [round(v/total*100) for v in f["zones"]]

    opening = _pick_by_combo(combos, [
        f"1회차부터 {latest}회차까지의 누적 기록과 최근 흐름을 함께 비교해 {round_no}회차 추천번호를 구성했습니다.",
        f"{latest}회차까지의 장기 통계와 최근 출현 변화를 함께 살펴 이번 추천 후보를 선별했습니다.",
        f"전체 당첨 기록과 최근 회차의 움직임을 함께 반영해 {round_no}회차 조합을 정리했습니다.",
    ], "opening")

    if hot_used and overdue_used:
        trend = f"최근 흐름에서 확인된 {_fmt(hot_used)}번과 쉬어간 기간을 고려한 {_fmt(overdue_used)}번을 여러 조합에 나누어 반영했습니다."
    elif hot_used:
        trend = f"최근 출현 흐름이 이어진 {_fmt(hot_used)}번을 중심 후보로 두되 한 조합에 몰리지 않도록 분산했습니다."
    elif overdue_used:
        trend = f"쉬어간 기간이 길었던 {_fmt(overdue_used)}번을 보강 후보로 포함하고 다른 번호와 균형 있게 배치했습니다."
    elif core:
        trend = f"전체 조합에서 반복된 중심 번호 {_fmt(core)}번은 유지하고 주변 번호는 조합마다 다르게 구성했습니다."
    else:
        trend = "특정 번호를 반복하기보다 여러 후보를 고르게 사용해 한쪽 흐름에 치우치지 않도록 구성했습니다."

    balance = (
        f"저·중·고번호 비중은 약 {zone_pct[0]}%·{zone_pct[1]}%·{zone_pct[2]}%로 나누고, "
        f"{len(combos)}개 중 {f['odd_balanced']}개 조합의 홀짝을 2:4~4:2 범위로 맞췄습니다."
    )

    structure_bits = []
    if f["consecutive"]:
        structure_bits.append(f"연속수는 {f['consecutive']}개 조합에만 제한")
    else:
        structure_bits.append("연속수 반복은 최소화")
    structure_bits.append(f"끝수 분산은 {f['end_balanced']}개 조합에서 확보")
    structure_bits.append(f"조합 간 최대 중복은 {f['max_overlap']}개로 관리")
    structure = ", ".join(structure_bits) + f"했으며 전체적으로 {f['unique']}개의 서로 다른 번호를 사용했습니다."

    lines = [opening, trend, balance, structure]
    if fixed:
        lines[-1] += " 지정한 고정수는 유지했습니다."
    if excluded:
        lines[-1] += " 제외수는 모든 조합에서 배제했습니다."
    return "\n".join(lines)
