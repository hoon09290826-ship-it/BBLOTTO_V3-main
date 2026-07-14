from __future__ import annotations

import hashlib
import statistics
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .cache_engine import get_analysis_cache

EXPLANATION_ENGINE_VERSION = "BBLOTTO_AI_EXPLANATION_V13_03"


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pick(seed: str, options: Sequence[str]) -> str:
    if not options:
        return ""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return options[int.from_bytes(digest[:8], "big") % len(options)]


def _mapping_value(mapping: Mapping[str, Any], number: int) -> float:
    return _as_float(mapping.get(str(number), mapping.get(number, 0.0)))


def _numbers(detail: Mapping[str, Any]) -> List[int]:
    raw = detail.get("numbers") or detail.get("nums") or detail.get("combo") or []
    result: List[int] = []
    for value in raw if isinstance(raw, (list, tuple, set)) else []:
        number = _as_int(value, -1)
        if 1 <= number <= 45 and number not in result:
            result.append(number)
    return sorted(result) if len(result) == 6 else []


def _valid_details(details: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for detail in details or []:
        combo = _numbers(detail)
        if combo:
            item = dict(detail)
            item["numbers"] = combo
            result.append(item)
    return result


def _zone(number: int) -> int:
    return 0 if number <= 15 else 1 if number <= 30 else 2


def _zone_label(index: int) -> str:
    return ("1~15번대", "16~30번대", "31~45번대")[index]


def _zone_flow(cache: Mapping[str, Any], key: str) -> List[float]:
    mapping = cache.get(key) or {}
    totals = [0.0, 0.0, 0.0]
    for number in range(1, 46):
        totals[_zone(number)] += _mapping_value(mapping, number)
    return totals


def _trend_metrics(cache: Mapping[str, Any]) -> Dict[str, Any]:
    f10 = _zone_flow(cache, "frequency10")
    f30 = _zone_flow(cache, "frequency30")
    f100 = _zone_flow(cache, "frequency100")
    # Window size differences are normalized per draw so zones are comparable.
    normalized = [
        (f10[i] / 10.0) * 0.50 + (f30[i] / 30.0) * 0.32 + (f100[i] / 100.0) * 0.18
        for i in range(3)
    ]
    order = sorted(range(3), key=lambda idx: normalized[idx], reverse=True)
    lead, support, weak = order[0], order[1], order[2]
    spread = normalized[lead] - normalized[weak]
    return {
        "lead": lead,
        "support": support,
        "weak": weak,
        "spread": spread,
        "normalized": normalized,
    }


def _evidence_map(details: Sequence[Mapping[str, Any]]) -> Dict[int, Dict[str, Any]]:
    evidence: Dict[int, Dict[str, Any]] = {}
    for detail in details:
        for item in detail.get("number_evidence") or []:
            if not isinstance(item, Mapping):
                continue
            number = _as_int(item.get("number"), -1)
            if not 1 <= number <= 45:
                continue
            current = evidence.setdefault(number, {})
            for key, value in item.items():
                if key not in current or current[key] in (None, "", [], 0):
                    current[key] = value
    return evidence


def _portfolio_metrics(details: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    combos = [list(detail["numbers"]) for detail in details]
    sums = [sum(combo) for combo in combos]
    odds = [sum(number % 2 for number in combo) for combo in combos]
    zones = [
        (
            sum(number <= 15 for number in combo),
            sum(16 <= number <= 30 for number in combo),
            sum(number >= 31 for number in combo),
        )
        for combo in combos
    ]
    overlaps = [
        len(set(left) & set(right))
        for index, left in enumerate(combos)
        for right in combos[index + 1 :]
    ]
    consecutive = sum(
        1 for combo in combos for left, right in zip(combo, combo[1:]) if right - left == 1
    )
    end_counts = Counter(number % 10 for combo in combos for number in combo)
    use_counts = Counter(number for combo in combos for number in combo)
    return {
        "combos": combos,
        "sum_min": min(sums),
        "sum_max": max(sums),
        "sum_median": round(statistics.median(sums)),
        "odd_mode": Counter(odds).most_common(1)[0][0],
        "zone_totals": [sum(row[i] for row in zones) for i in range(3)],
        "max_overlap": max(overlaps, default=0),
        "consecutive": consecutive,
        "max_end_repeat": max(end_counts.values(), default=0),
        "unique_numbers": len(use_counts),
        "max_number_use": max(use_counts.values(), default=0),
    }


def _role_metrics(evidence: Mapping[int, Mapping[str, Any]], portfolio: Mapping[str, Any]) -> Counter:
    roles: Counter = Counter()
    used = {number for combo in portfolio["combos"] for number in combo}
    for number in used:
        roles[str(evidence.get(number, {}).get("role") or "균형수")] += 1
    return roles


def _trend_line(round_no: int, cache: Mapping[str, Any], seed: str) -> str:
    trend = _trend_metrics(cache)
    lead = _zone_label(trend["lead"])
    support = _zone_label(trend["support"])
    weak = _zone_label(trend["weak"])
    if trend["spread"] >= 0.16:
        return _pick(seed + "trend-strong", [
            f"이번 {round_no}회차는 최근 10·30·100회 흐름을 함께 비교했을 때 {lead}의 출현 강도가 가장 높고 {weak} 구간은 상대적으로 약해, 강한 구간을 중심으로 부족 구간을 보완했습니다.",
            f"최근 단기·중기 흐름에서는 {lead}가 뚜렷하게 앞서고 {weak}의 비중이 낮아, 이번 추천은 우세 구간을 활용하되 한쪽 쏠림은 제한했습니다.",
        ])
    return _pick(seed + "trend-balanced", [
        f"이번 {round_no}회차는 최근 10·30·100회에서 {lead}와 {support}의 흐름 차이가 크지 않아 특정 번호대보다 구간 분산을 우선했습니다.",
        f"최근 기간별 출현 흐름이 한 구간에만 집중되지 않아 이번 {round_no}회차는 {lead}와 {support}를 함께 활용하는 균형형 후보군으로 구성했습니다.",
    ])


def _selection_line(roles: Counter, cache: Mapping[str, Any], seed: str) -> str:
    hot = roles.get("강세수", 0)
    rebound = roles.get("반등수", 0)
    balanced = roles.get("균형수", 0)
    overdue = cache.get("overdue") or []
    if hot and rebound:
        return _pick(seed + "select-mix", [
            f"후보군에는 최근 출현 점수가 높은 강세수 {hot}개와 미출현 간격이 누적된 반등수 {rebound}개를 함께 넣고, 균형수 {balanced}개로 변동 폭을 조절했습니다.",
            f"단기 상승 흐름의 강세수 {hot}개만 반복하지 않고 반등 후보 {rebound}개를 조합별로 나눠 배치해 최근 흐름과 장기 공백을 동시에 반영했습니다.",
        ])
    if rebound:
        return _pick(seed + "select-rebound", [
            f"최근 미출현 간격이 길어진 반등 후보 {rebound}개를 일부 조합에만 분산하고, 나머지는 장기 빈도가 안정적인 번호로 보완했습니다.",
            f"전체 이력 대비 공백이 누적된 후보군을 보완 축으로 사용하되, 반등수의 과도한 집중을 막아 조합별 위험을 나눴습니다.",
        ])
    if hot:
        return _pick(seed + "select-hot", [
            f"최근 빈도와 모멘텀이 함께 높은 강세수 {hot}개를 주축으로 삼되 같은 번호의 반복 사용을 제한해 조합 간 선택 폭을 유지했습니다.",
            f"최근 10·30회에서 흐름이 이어진 강세 후보를 중심으로 선별하고, 전체 누적 빈도가 안정적인 번호를 보조축으로 배치했습니다.",
        ])
    return _pick(seed + "select-neutral", [
        "최근 강세와 장기 공백 어느 한쪽 신호도 과도하게 우세하지 않아 전체 이력 점수와 기간별 빈도가 고른 번호를 중심으로 선별했습니다.",
        "후보별 단기·중기·전체 점수를 함께 비교해 급격한 편중보다 지속성이 있는 균형 후보를 우선했습니다.",
    ])


def _balance_line(portfolio: Mapping[str, Any], seed: str) -> str:
    odd = portfolio["odd_mode"]
    zone_totals = portfolio["zone_totals"]
    strong_zone = _zone_label(max(range(3), key=lambda idx: zone_totals[idx]))
    return _pick(seed + "balance", [
        f"실제 조합은 홀짝 {odd}:{6-odd} 형태를 중심으로 맞추고 합계를 {portfolio['sum_min']}~{portfolio['sum_max']} 범위에 분산해 극단적인 조합을 줄였습니다.",
        f"조합 합계의 중앙값은 약 {portfolio['sum_median']}이며, 홀짝은 주로 {odd}:{6-odd}로 구성하고 {strong_zone}의 과도한 집중은 포트폴리오 단계에서 조정했습니다.",
    ])


def _diversity_line(portfolio: Mapping[str, Any], details: Sequence[Mapping[str, Any]], seed: str) -> str:
    pair_strengths = [_as_float(detail.get("pair_strength")) for detail in details]
    avg_pair = sum(pair_strengths) / len(pair_strengths) if pair_strengths else 0.0
    if avg_pair >= 1.5:
        return _pick(seed + "div-pair", [
            f"동반출현 점수가 높은 번호쌍은 일부 조합에만 반영하고, 조합 간 최대 중복을 {portfolio['max_overlap']}개로 제한해 같은 패턴의 반복을 줄였습니다.",
            f"과거 동반출현 관계는 보조 근거로 활용했지만 전체 {portfolio['unique_numbers']}개 번호를 분산 사용해 특정 번호쌍에 의존하지 않도록 했습니다.",
        ])
    return _pick(seed + "div-basic", [
        f"조합 간 최대 중복은 {portfolio['max_overlap']}개로 관리하고 연속수는 전체 {portfolio['consecutive']}쌍만 제한적으로 사용해 서로 다른 형태를 확보했습니다.",
        f"전체 {portfolio['unique_numbers']}개 번호를 활용하면서 동일 끝수와 반복 번호의 집중을 낮춰 조합별 차이를 유지했습니다.",
    ])


def _condition_line(fixed: Any, excluded: Any) -> str:
    parts: List[str] = []
    if str(fixed or "").strip():
        parts.append("입력한 고정수는 모든 조합에 유지했습니다")
    if str(excluded or "").strip():
        parts.append("제외수는 후보 점수 계산과 최종 조합에서 모두 배제했습니다")
    return ". ".join(parts) + "." if parts else ""


def _number_reason(number: int, evidence: Mapping[int, Mapping[str, Any]]) -> str:
    item = evidence.get(number, {})
    role = str(item.get("role") or "균형수")
    f10 = _as_int(item.get("freq10"))
    f30 = _as_int(item.get("freq30"))
    gap = _as_int(item.get("gap"))
    if role == "강세수":
        return f"{number}번(강세수·최근 10회 {f10}회/30회 {f30}회)"
    if role == "반등수":
        return f"{number}번(반등수·{gap}회 미출현)"
    return f"{number}번(균형수·단기/중기 흐름 안정)"


def _actual_selection_line(details: Sequence[Mapping[str, Any]], evidence: Mapping[int, Mapping[str, Any]]) -> str:
    use_counts = Counter(number for detail in details for number in detail["numbers"])
    ranked = sorted(use_counts, key=lambda n: (-use_counts[n], -_as_float(evidence.get(n, {}).get("selection_score")), n))
    core = ranked[: min(4, len(ranked))]
    if not core:
        return "실제 생성된 조합에서 공통 핵심수를 확인하지 못했습니다."
    described = ", ".join(_number_reason(n, evidence) for n in core)
    counts = ", ".join(f"{n}번 {use_counts[n]}개 조합" for n in core)
    return f"실제 추천번호에서는 {described}을 핵심 축으로 선택했으며, 사용 비중은 {counts}입니다."


def _actual_combo_line(details: Sequence[Mapping[str, Any]]) -> str:
    ranked = sorted(details, key=lambda d: (-_as_float(d.get("score")), d["numbers"]))
    best = ranked[0]
    combo = best["numbers"]
    combo_text = "·".join(map(str, combo))
    odd = _as_int(best.get("odd"), sum(n % 2 for n in combo))
    even = _as_int(best.get("even"), 6 - odd)
    zones = best.get("zones") or [sum(n <= 15 for n in combo), sum(16 <= n <= 30 for n in combo), sum(n >= 31 for n in combo)]
    total = _as_int(best.get("sum"), sum(combo))
    ac = _as_int(best.get("ac"))
    kind = str(best.get("type") or best.get("strategy") or "균형형")
    return f"가장 높은 평가를 받은 [{combo_text}] 조합은 {kind}으로, 홀짝 {odd}:{even}·구간 {zones[0]}-{zones[1]}-{zones[2]}·합계 {total}·AC {ac} 조건을 충족해 최종 선별됐습니다."


def _actual_portfolio_line(portfolio: Mapping[str, Any], details: Sequence[Mapping[str, Any]]) -> str:
    lowest = min(details, key=lambda d: (_as_float(d.get("score")), d["numbers"]))
    low_text = "·".join(map(str, lowest["numbers"]))
    return (
        f"전체 추천 조합은 합계 {portfolio['sum_min']}~{portfolio['sum_max']}, 홀짝 중심형 {portfolio['odd_mode']}:{6-portfolio['odd_mode']}로 분산했고, "
        f"조합 간 최대 중복을 {portfolio['max_overlap']}개로 제한했습니다. [{low_text}] 같은 보완 조합도 포함해 동일 번호 편중을 줄였습니다."
    )


def _actual_pair_line(details: Sequence[Mapping[str, Any]], portfolio: Mapping[str, Any]) -> str:
    pair_best = max(details, key=lambda d: (_as_float(d.get("pair_strength")), _as_float(d.get("score"))))
    combo_text = "·".join(map(str, pair_best["numbers"]))
    pair_strength = _as_float(pair_best.get("pair_strength"))
    if pair_strength > 0:
        return f"동반출현 근거는 [{combo_text}] 조합에 가장 강하게 반영됐고(점수 {pair_strength:.1f}), 전체에서는 {portfolio['unique_numbers']}개 번호를 사용해 특정 번호쌍의 반복을 억제했습니다."
    return f"동반출현은 보조 기준으로만 사용하고, 전체 {portfolio['unique_numbers']}개 번호와 연속수 {portfolio['consecutive']}쌍을 분산해 조합별 형태를 다르게 구성했습니다."


def build_round_analysis(
    round_no: int,
    stats: Mapping[str, Any] | None,
    mode: str,
    fixed: Any,
    excluded: Any,
    details: Sequence[Mapping[str, Any]],
) -> str:
    """Explain the numbers that were actually generated, not a generic trend summary."""
    valid = _valid_details(details)
    if not valid:
        return "추천 조합의 분석 근거가 없어 설명을 만들 수 없습니다. 번호를 다시 생성해 주세요."

    portfolio = _portfolio_metrics(valid)
    evidence = _evidence_map(valid)
    actual_round = _as_int(round_no, 1)

    lines = [
        f"{actual_round}회차 추천번호 생성 결과를 기준으로 설명합니다. " + _actual_selection_line(valid, evidence),
        _actual_combo_line(valid),
        _actual_portfolio_line(portfolio, valid),
        _actual_pair_line(valid, portfolio),
    ]
    condition = _condition_line(fixed, excluded)
    if condition:
        lines.append(condition)
    return "\n".join(line for line in lines[:5] if line)

