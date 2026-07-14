"""BBLOTTO round-focused recommendation explanation engine.

This module never generates numbers.  It converts the factual evidence emitted by
``recommendation_engine.py`` into a concise 3-5 line Korean summary explaining why
this round's portfolio was constructed in that way.
"""
from __future__ import annotations

import collections
import hashlib
import statistics
from typing import Any, Dict, Iterable, List, Sequence, Tuple


def _numbers(detail: Dict[str, Any]) -> List[int]:
    raw = detail.get("numbers") or detail.get("nums") or detail.get("combo") or []
    try:
        nums = sorted({int(value) for value in raw if 1 <= int(value) <= 45})
    except (TypeError, ValueError):
        return []
    return nums if len(nums) == 6 else []


def _choice(seed: str, options: Sequence[str]) -> str:
    if not options:
        return ""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return options[int.from_bytes(digest[:4], "big") % len(options)]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _evidence(details: Iterable[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    merged: Dict[int, Dict[str, Any]] = {}
    for detail in details or []:
        for item in detail.get("number_evidence") or []:
            number = _int(item.get("number"), -1)
            if not 1 <= number <= 45:
                continue
            current = merged.setdefault(number, {})
            for key, value in item.items():
                if key not in current or current[key] in (None, "", [], 0):
                    current[key] = value
    return merged


def _zones(nums: Sequence[int]) -> Tuple[int, int, int]:
    return (
        sum(1 for n in nums if n <= 15),
        sum(1 for n in nums if 16 <= n <= 30),
        sum(1 for n in nums if n >= 31),
    )


def _consecutive_count(nums: Sequence[int]) -> int:
    return sum(1 for a, b in zip(nums, nums[1:]) if b - a == 1)


def _role_counts(ev: Dict[int, Dict[str, Any]], used: Iterable[int]) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    for number in used:
        role = str(ev.get(number, {}).get("role") or "균형수")
        counts[role] += 1
    return counts


def _ranked_numbers(combos: Sequence[Sequence[int]], ev: Dict[int, Dict[str, Any]]) -> List[int]:
    usage = collections.Counter(n for combo in combos for n in combo)

    def score(number: int) -> Tuple[float, int]:
        item = ev.get(number, {})
        engine_score = float(item.get("selection_score") or 0.0)
        f10 = _int(item.get("freq10"))
        f30 = _int(item.get("freq30"))
        f100 = _int(item.get("freq100"))
        gap = _int(item.get("gap"))
        role = str(item.get("role") or "")
        role_bonus = 3.0 if role == "강세수" else 2.0 if role == "반등수" else 1.0
        return (
            usage[number] * 20.0 + engine_score + f10 * 4.0 + f30 * 1.5 + f100 * 0.2 + min(gap, 18) * 0.35 + role_bonus,
            -number,
        )

    return sorted(usage, key=score, reverse=True)


def _format_range_labels(zone_totals: Sequence[int]) -> Tuple[str, str]:
    labels = ("1~15번", "16~30번", "31~45번")
    order = sorted(range(3), key=lambda idx: (zone_totals[idx], -idx), reverse=True)
    return labels[order[0]], labels[order[-1]]


def _trend_line(round_no: int, core: Sequence[int], ev: Dict[int, Dict[str, Any]], seed: str) -> str:
    """Describe the round trend first; mention individual numbers only as evidence."""
    hot = [n for n in core if str(ev.get(n, {}).get("role") or "") == "강세수"]
    rebound = [n for n in core if str(ev.get(n, {}).get("role") or "") == "반등수"]

    zone_scores = [0.0, 0.0, 0.0]
    zone_labels = ("1~15번", "16~30번", "31~45번")
    for number, item in ev.items():
        idx = 0 if number <= 15 else 1 if number <= 30 else 2
        zone_scores[idx] += (
            _int(item.get("freq10")) * 4.0
            + _int(item.get("freq30")) * 1.5
            + _int(item.get("freq100")) * 0.25
            + float(item.get("selection_score") or 0.0) * 0.05
        )
    order = sorted(range(3), key=lambda idx: zone_scores[idx], reverse=True)
    lead_zone = zone_labels[order[0]]
    support_zone = zone_labels[order[1]]

    if hot and rebound:
        return _choice(seed + "trend-mix", [
            f"이번 {round_no}회차는 최근 10·30회에서 흐름이 유지된 번호대와 장기 미출현 반등 후보를 함께 반영한 혼합형 분석이 우세했습니다.",
            f"최근 단기 강세와 누적 미출현 흐름이 동시에 나타나 이번 {round_no}회차는 강세수 중심에 반등 후보를 분산하는 방식으로 구성했습니다.",
            f"이번 회차 데이터에서는 최근 출현 강도와 공백 누적 신호가 함께 포착돼 한쪽 흐름에 치우치지 않는 혼합 구성이 적합하게 나타났습니다.",
        ])
    if hot:
        return _choice(seed + "trend-hot", [
            f"이번 {round_no}회차는 최근 10·30회에서 출현 강도가 이어진 {lead_zone} 흐름이 상대적으로 우세해 해당 구간을 중심으로 반영했습니다.",
            f"최근 단기·중기 빈도를 비교한 결과 {lead_zone}와 {support_zone}의 흐름이 안정적으로 유지돼 이번 추천의 중심 구간으로 활용했습니다.",
            f"이번 회차는 최근 출현 빈도와 선택 점수가 함께 높아진 번호대를 우선 반영하되 특정 번호의 과도한 반복은 줄였습니다.",
        ])
    if rebound:
        return _choice(seed + "trend-rebound", [
            f"이번 {round_no}회차는 최근 미출현 간격이 누적된 번호들의 반등 신호가 상대적으로 높아 일부 조합에 보완 후보로 반영했습니다.",
            f"최근 강세수만 반복하기보다 장기 공백이 길어진 번호대를 함께 살펴 이번 회차의 변동 가능성을 조합에 나눠 담았습니다.",
            f"전체 이력과 최근 흐름을 비교한 결과 미출현 공백이 누적된 후보군의 반등 가능성이 높아져 보완 축으로 활용했습니다.",
        ])
    return _choice(seed + "trend-neutral", [
        f"이번 {round_no}회차는 1회차부터 최신 회차까지의 전체 흐름과 최근 10·30·100회 가중치를 함께 비교해 균형형 후보군을 선별했습니다.",
        f"전체 누적 통계와 최근 흐름 사이의 편차가 크지 않아 이번 회차는 특정 구간보다 분산과 조합 균형을 우선했습니다.",
        f"이번 회차는 장기 빈도와 최근 출현 흐름을 함께 반영해 어느 한 번호대에 과도하게 집중되지 않는 후보군을 구성했습니다.",
    ])

def _balance_line(combos: Sequence[Sequence[int]], seed: str) -> str:
    odds = [sum(n % 2 for n in combo) for combo in combos]
    sums = [sum(combo) for combo in combos]
    zones = [_zones(combo) for combo in combos]
    zone_totals = [sum(z[idx] for z in zones) for idx in range(3)]
    high_zone, low_zone = _format_range_labels(zone_totals)
    odd_mode = collections.Counter(odds).most_common(1)[0][0]
    median_sum = round(statistics.median(sums))

    return _choice(seed + "balance", [
        f"조합 구조는 홀수 {odd_mode}개 비중을 중심으로 맞추고 합계는 {min(sums)}~{max(sums)} 범위에 분산해 최근 당첨 조합의 일반적인 균형을 유지했습니다.",
        f"홀짝은 주로 {odd_mode}:{6-odd_mode} 형태로 구성했으며 조합 합계의 중앙값은 약 {median_sum}로, 과도하게 낮거나 높은 조합을 줄였습니다.",
        f"번호대는 {high_zone}의 흐름을 반영하면서도 {low_zone}을 보완해 특정 구간 쏠림을 줄였고, 합계는 {min(sums)}~{max(sums)} 사이로 조정했습니다.",
    ])


def _diversity_line(combos: Sequence[Sequence[int]], ev: Dict[int, Dict[str, Any]], seed: str) -> str:
    overlaps = [len(set(a) & set(b)) for idx, a in enumerate(combos) for b in combos[idx + 1 :]]
    max_overlap = max(overlaps, default=0)
    consecutive = sum(_consecutive_count(combo) for combo in combos)
    endings = collections.Counter(n % 10 for combo in combos for n in combo)
    max_ending = max(endings.values(), default=0)
    used = len({n for combo in combos for n in combo})
    pairs: List[Tuple[int, int, int]] = []
    for number, item in ev.items():
        for partner in item.get("partners") or []:
            other = _int(partner.get("number"), -1)
            count = _int(partner.get("count"))
            if number < other <= 45 and count > 0:
                pairs.append((count, number, other))
    pairs = sorted(set(pairs), reverse=True)

    if pairs:
        pair_text = ", ".join(f"{a}-{b}번" for _, a, b in pairs[:2])
        return _choice(seed + "div-pairs", [
            f"과거 동반출현이 비교적 잦았던 {pair_text} 연결은 일부 조합에만 반영하고, 조합 간 번호 중복은 최대 {max_overlap}개 수준으로 제한했습니다.",
            f"동반출현 자료에서는 {pair_text} 관계를 참고했지만 같은 번호쌍의 반복을 줄여 전체 {used}개 번호가 고르게 활용되도록 했습니다.",
        ])

    return _choice(seed + "div", [
        f"조합 간 최대 중복은 {max_overlap}개로 관리하고 연속수는 전체 {consecutive}쌍만 제한적으로 사용해 서로 다른 형태의 조합을 확보했습니다.",
        f"전체 추천에는 {used}개 번호를 활용했으며 같은 끝수의 과도한 반복과 조합 간 유사도를 낮춰 선택 범위를 넓혔습니다.",
        f"연속수와 동일 끝수는 필요한 조합에만 제한적으로 배치하고, 조합 간 최대 중복을 {max_overlap}개로 낮춰 다양성을 유지했습니다.",
    ])


def _condition_line(fixed: Any, excluded: Any) -> str:
    fragments: List[str] = []
    if fixed:
        fragments.append("입력한 고정수는 모든 조합의 공통 기준으로 유지했습니다")
    if excluded:
        fragments.append("제외수는 후보 선별과 최종 결과에서 모두 제거했습니다")
    return ", ".join(fragments) + "." if fragments else ""


def build_evidence_analysis(
    round_no: int,
    stats: Dict[str, Any],
    mode: str,
    fixed: Any,
    excluded: Any,
    details: List[Dict[str, Any]],
) -> str:
    """Return a factual 3-5 line round summary based on generated combinations."""
    combos = [_numbers(detail) for detail in details or []]
    combos = [combo for combo in combos if combo]
    if not combos:
        return "추천 조합의 분석 근거를 확인할 수 없습니다. 번호를 다시 생성해 주세요."

    ev = _evidence(details)
    ranked = _ranked_numbers(combos, ev)
    core = ranked[:4]
    seed = f"{round_no}|{mode}|{combos}|{[(n, ev.get(n, {})) for n in sorted(ev)]}"

    lines = [
        _trend_line(round_no, core, ev, seed),
        _balance_line(combos, seed),
        _diversity_line(combos, ev, seed),
    ]

    roles = _role_counts(ev, {n for combo in combos for n in combo})
    hot_count = roles.get("강세수", 0)
    rebound_count = roles.get("반등수", 0)
    balanced_count = roles.get("균형수", 0)
    if hot_count or rebound_count:
        lines.insert(
            1,
            _choice(seed + "roles", [
                f"선별된 번호군은 강세수 {hot_count}개, 반등수 {rebound_count}개, 균형수 {balanced_count}개로 구성해 단기 흐름과 장기 공백을 동시에 반영했습니다.",
                f"전체 후보에서 최근 강세수 {hot_count}개와 반등 후보 {rebound_count}개를 함께 사용하고, 나머지는 구간과 조합 균형을 보완하는 번호로 채웠습니다.",
                f"추천에 활용된 번호는 강세 흐름 {hot_count}개와 반등 흐름 {rebound_count}개를 중심으로 분류해 조합마다 역할이 겹치지 않도록 배치했습니다.",
            ]),
        )

    condition = _condition_line(fixed, excluded)
    if condition:
        lines.append(condition)

    # Keep the result concise: 3 to 5 factual lines only.
    return "\n".join(line for line in lines[:5] if line)


def build_recommendation_analysis(round_no: int, details: List[Dict[str, Any]]) -> str:
    """Compatibility helper returning the same concise portfolio explanation."""
    return build_evidence_analysis(round_no, {}, "balanced", None, None, details)
