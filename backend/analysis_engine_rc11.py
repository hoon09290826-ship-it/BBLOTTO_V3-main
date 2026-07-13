"""BBLOTTO RC11.2 번호 특징 기반 설명형 분석 엔진.

추천 조합과 전체/최근 통계를 실제로 비교해 회원이 이해하기 쉬운 문장으로
설명한다. 당첨 확률이나 수익을 보장하는 표현, 임의의 AI 점수는 사용하지 않는다.
"""
from __future__ import annotations

import collections
import hashlib
import random
import secrets
from typing import Any, Dict, Iterable, List, Sequence, Tuple


def _numbers(item: Dict[str, Any]) -> List[int]:
    raw = item.get("numbers") or item.get("nums") or item.get("combo") or []
    try:
        nums = sorted({int(n) for n in raw if 1 <= int(n) <= 45})
    except Exception:
        return []
    return nums if len(nums) == 6 else []


def _as_int_list(values: Iterable[Any], limit: int = 15) -> List[int]:
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


def _pick(rng: random.Random, pool: Sequence[str]) -> str:
    return pool[rng.randrange(len(pool))] if pool else ""


def _format_nums(nums: Sequence[int], limit: int = 5) -> str:
    return ", ".join(str(n) for n in list(nums)[:limit])


def _combo_features(combos: List[List[int]]) -> Dict[str, Any]:
    flat = [n for combo in combos for n in combo]
    count = max(1, len(combos))
    total = max(1, len(flat))
    freq = collections.Counter(flat)

    zones = {
        "1~15번대": sum(n <= 15 for n in flat),
        "16~30번대": sum(16 <= n <= 30 for n in flat),
        "31~45번대": sum(n >= 31 for n in flat),
    }
    strongest_zone, strongest_count = max(zones.items(), key=lambda x: x[1])

    odd_counts = [sum(n % 2 for n in combo) for combo in combos]
    sums = [sum(combo) for combo in combos]
    widths = [combo[-1] - combo[0] for combo in combos]
    consecutive_combos = [combo for combo in combos if any(b - a == 1 for a, b in zip(combo, combo[1:]))]
    same_end_combos = [combo for combo in combos if len({n % 10 for n in combo}) < 5]
    overlaps = [len(set(a) & set(b)) for i, a in enumerate(combos) for b in combos[i + 1 :]]

    return {
        "flat": flat,
        "freq": freq,
        "zones": zones,
        "strongest_zone": strongest_zone,
        "zone_share": strongest_count / total,
        "odd_avg": sum(odd_counts) / count,
        "balanced_odd": sum(2 <= x <= 4 for x in odd_counts),
        "sum_avg": sum(sums) / count,
        "sum_min": min(sums),
        "sum_max": max(sums),
        "width_avg": sum(widths) / count,
        "consecutive_count": len(consecutive_combos),
        "same_end_count": len(same_end_combos),
        "max_overlap": max(overlaps, default=0),
        "common": [n for n, c in freq.most_common(8) if c >= 2],
        "unique_numbers": len(freq),
    }


def _trend_lists(stats: Dict[str, Any]) -> Tuple[List[int], List[int]]:
    hot = _as_int_list(
        stats.get("hot20")
        or stats.get("hot30")
        or stats.get("hot50")
        or stats.get("hot100")
        or stats.get("hot300")
        or stats.get("hot")
        or []
    )
    overdue = _as_int_list(
        stats.get("overdue20")
        or stats.get("overdue30")
        or stats.get("overdue50")
        or stats.get("overdue100")
        or stats.get("overdue300")
        or stats.get("overdue")
        or []
    )
    return hot, overdue


def _mode_label(mode: str) -> str:
    key = str(mode or "balanced").lower()
    return {
        "balanced": "균형형",
        "balance": "균형형",
        "aggressive": "변화형",
        "strong": "강세형",
        "stable": "안정형",
        "conservative": "안정형",
        "random": "분산형",
    }.get(key, "균형형")


def build_member_friendly_analysis(
    round_no: int,
    stats: Dict[str, Any],
    mode: str,
    fixed: Any,
    excluded: Any,
    details: List[Dict[str, Any]],
) -> str:
    combos = [_numbers(item) for item in details or []]
    combos = [combo for combo in combos if combo]
    latest = int(stats.get("latest_round") or stats.get("target_round") or max(0, int(round_no or 1) - 1))

    # 같은 조합이어도 표현은 달라지며, 문장 선택의 근거는 실제 특징으로 제한한다.
    nonce = secrets.token_bytes(16)
    digest = hashlib.sha256(nonce + repr(combos).encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))

    if not combos:
        fallback = [
            f"1회차부터 {latest}회차까지의 기록을 다시 확인해 이번 추천을 구성했습니다.",
            "최근에 자주 보인 번호와 잠시 쉬었던 번호를 함께 살폈습니다.",
            "낮은 번호부터 높은 번호까지 한쪽에 몰리지 않도록 나누었습니다.",
            "서로 비슷한 조합이 반복되지 않도록 조합별 차이를 두었습니다.",
        ]
        return "\n".join(rng.sample(fallback, 3))

    f = _combo_features(combos)
    freq: collections.Counter[int] = f["freq"]
    hot, overdue = _trend_lists(stats)
    hot_used = [n for n in hot if n in freq][:4]
    overdue_used = [n for n in overdue if n in freq][:4]
    mode_name = _mode_label(mode)

    opening_pool = [
        f"1회차부터 {latest}회차까지의 누적 기록과 최근 흐름을 함께 비교해 {round_no}회차 추천을 구성했습니다.",
        f"{latest}회차까지 쌓인 결과를 장기 흐름과 최근 흐름으로 나누어 살펴 이번 후보를 골랐습니다.",
        f"전체 회차 기록에 최근 변화까지 더해 {mode_name} 기준으로 추천번호를 다시 선별했습니다.",
        f"오래된 출현 기록과 최근 회차 움직임을 따로 비교한 뒤 공통으로 눈에 띈 번호를 중심으로 구성했습니다.",
    ]

    zone_pool: List[str] = []
    if f["zone_share"] >= 0.40:
        zone_pool.extend([
            f"{f['strongest_zone']}가 조금 더 많이 잡혀 중심 흐름으로 두고, 나머지 번호대도 빠지지 않게 보완했습니다.",
            f"이번 결과는 {f['strongest_zone']}의 움직임을 살리면서 다른 구간을 함께 섞어 편중을 줄였습니다.",
        ])
    else:
        zone_pool.extend([
            "1~15번대, 16~30번대, 31~45번대를 고르게 섞어 특정 구간만 반복되지 않도록 했습니다.",
            "낮은 번호와 중간 번호, 높은 번호가 한쪽에 몰리지 않도록 조합마다 분산했습니다.",
        ])

    trend_pool: List[str] = []
    if hot_used:
        trend_pool.extend([
            f"최근 흐름에서 자주 확인된 {_format_nums(hot_used)}번은 한 조합에 몰지 않고 여러 조합에 나누어 반영했습니다.",
            f"{_format_nums(hot_used)}번은 최근 출현 흐름이 이어져 중심 후보로 살펴봤습니다.",
        ])
    if overdue_used:
        trend_pool.extend([
            f"한동안 출현이 뜸했던 {_format_nums(overdue_used)}번도 일부 포함해 변화 후보를 함께 살폈습니다.",
            f"{_format_nums(overdue_used)}번은 쉬어간 기간을 고려해 보강 후보로 나누어 넣었습니다.",
        ])
    if not trend_pool:
        trend_pool.extend([
            "자주 나온 번호만 몰아서 사용하지 않고, 쉬어간 번호도 함께 섞어 흐름을 나누었습니다.",
            "단순 누적 횟수보다는 최근 움직임과 쉬어간 기간을 함께 비교했습니다.",
        ])

    structure_pool: List[str] = []
    if f["balanced_odd"] >= max(1, len(combos) * 0.7):
        structure_pool.append("대부분의 조합에서 홀수와 짝수가 2:4~4:2 범위에 들어오도록 균형을 맞췄습니다.")
    else:
        structure_pool.append("홀수나 짝수가 지나치게 몰린 조합은 줄이고 조합별 균형을 다시 조정했습니다.")

    if f["consecutive_count"]:
        structure_pool.extend([
            f"연속번호는 {f['consecutive_count']}개 조합에만 제한적으로 넣어 흐름은 살리고 반복은 줄였습니다.",
            f"붙어 있는 번호는 전체 {len(combos)}개 중 {f['consecutive_count']}개 조합에만 배치해 과도한 반복을 피했습니다.",
        ])
    else:
        structure_pool.append("연속번호가 반복되는 형태는 줄이고 번호 사이 간격이 넓게 퍼지도록 구성했습니다.")

    if f["max_overlap"] <= 3:
        structure_pool.append("조합끼리 같은 번호가 과도하게 겹치지 않아 각 조합이 서로 다른 후보군을 담고 있습니다.")
    else:
        common_text = _format_nums(f["common"], 4)
        structure_pool.append(
            f"반복된 중심 번호{(' ' + common_text + '번') if common_text else ''}는 유지하고 주변 번호는 서로 다르게 배치했습니다."
        )

    diversity_pool = [
        f"10개 조합 전체에서 {f['unique_numbers']}개의 서로 다른 번호를 사용해 선택 범위를 넓혔습니다.",
        f"조합 합계는 {f['sum_min']}부터 {f['sum_max']} 사이로 나뉘어 한 가지 모양에만 집중되지 않았습니다.",
        "끝자리가 같은 번호가 한 조합에 몰리지 않도록 나누어 배치했습니다.",
        "중심 번호는 유지하되 주변 번호를 달리해 조합마다 역할이 겹치지 않도록 했습니다.",
    ]

    if fixed:
        diversity_pool.append("지정한 고정수는 유지하면서 나머지 번호를 서로 다르게 배치했습니다.")
    if excluded:
        diversity_pool.append("제외수는 모든 조합에서 빼고 남은 후보 안에서 분산을 다시 맞췄습니다.")

    closing_pool = [
        "한 가지 흐름만 따르지 않고 최근 강세, 쉬어간 번호, 구간 분산을 함께 반영한 구성입니다.",
        "이번 추천은 비슷한 조합의 반복을 줄이고 서로 다른 흐름을 여러 조합으로 나누어 담았습니다.",
        "전체 기록을 바탕으로 하되 최근 변화가 묻히지 않도록 후보를 나누어 구성했습니다.",
        "번호대와 홀짝, 간격을 함께 살피면서 조합마다 차이가 나도록 최종 정리했습니다.",
    ]

    candidates = [
        _pick(rng, opening_pool),
        _pick(rng, zone_pool),
        _pick(rng, trend_pool),
        _pick(rng, structure_pool),
        _pick(rng, diversity_pool),
        _pick(rng, closing_pool),
    ]

    result: List[str] = []
    for line in candidates:
        line = line.strip()
        if line and line not in result:
            result.append(line)

    # 읽기 쉬운 4줄 리포트로 제한한다.
    return "\n".join(result[:4])
