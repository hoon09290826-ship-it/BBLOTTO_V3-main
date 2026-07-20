"""BBLOTTO recommendation explanation engine.

This module is the single owner of member-facing analysis text.  Number
generation code supplies final combinations and evidence; this module explains
why visible numbers were selected without generating or changing numbers.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Sequence


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _numbers(item: Mapping[str, Any]) -> List[int]:
    raw = item.get("numbers") or item.get("nums") or item.get("combo") or []
    nums = sorted({_int(value, -1) for value in raw if 1 <= _int(value, -1) <= 45})
    return nums if len(nums) == 6 else []


def _details_by_combo(details: Iterable[Mapping[str, Any]]) -> Dict[tuple, Dict[str, Any]]:
    result: Dict[tuple, Dict[str, Any]] = {}
    for source in details or []:
        if not isinstance(source, Mapping):
            continue
        nums = _numbers(source)
        if nums:
            result[tuple(nums)] = dict(source)
    return result


def _evidence_by_number(details: Iterable[Mapping[str, Any]]) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    for detail in details or []:
        for source in detail.get("number_evidence") or []:
            if not isinstance(source, Mapping):
                continue
            number = _int(source.get("number"), -1)
            if 1 <= number <= 45:
                current = result.get(number)
                if current is None or _float(source.get("selection_score")) > _float(current.get("selection_score")):
                    result[number] = dict(source)
    return result


def _reason(number: int, evidence: Mapping[int, Mapping[str, Any]], usage: int | None = None) -> str:
    ev = evidence.get(number, {})
    factors: List[str] = []
    hot_rank = _int(ev.get("hot_rank"), 999)
    overdue_rank = _int(ev.get("overdue_rank"), 999)
    cold_rank = _int(ev.get("cold_rank"), 999)
    momentum = _float(ev.get("momentum"))
    gap = _int(ev.get("gap"))
    freq10, freq30 = _int(ev.get("freq10")), _int(ev.get("freq30"))
    if hot_rank <= 15:
        factors.append(f"HOT {hot_rank}위")
    if momentum > 0.04:
        factors.append(f"상승 모멘텀 +{momentum:.3f}")
    if overdue_rank <= 15 or gap >= 7:
        factors.append(f"{gap}회 미출현 반등")
    if cold_rank <= 12:
        factors.append(f"COLD {cold_rank}위 보강")
    if not factors and (freq10 or freq30):
        factors.append(f"최근 10회 {freq10}회·30회 {freq30}회 출현")
    selection_score = _float(ev.get("selection_score"))
    factors.append(f"가중치 {selection_score:.1f}")
    used = f"·{usage}개 조합 반영" if usage else ""
    role = str(ev.get("role") or "후보수")
    return f"{number}번({role}·{'·'.join(factors[:3])}{used})"


def _pair_basis(detail: Mapping[str, Any]) -> str:
    combo_evidence = detail.get("combo_evidence") or {}
    pairs = combo_evidence.get("pair_highlights") or []
    if pairs and isinstance(pairs[0], Mapping):
        nums = pairs[0].get("numbers") or []
        if len(nums) == 2:
            count = _int(pairs[0].get("count"), _int(pairs[0].get("frequency")))
            count_text = f" {count}회" if count else ""
            return f"{nums[0]}-{nums[1]} 동반출현{count_text}"
    return f"동반출현 평가 {_float(detail.get('pair_strength')):.1f}"


def build_professional_analysis(
    round_no: int,
    stats: Mapping[str, Any] | None,
    mode: str,
    fixed: Any,
    excluded: Any,
    combos: Sequence[Sequence[int]],
    details: Sequence[Mapping[str, Any]],
) -> str:
    final_combos = [sorted({_int(n, -1) for n in combo if 1 <= _int(n, -1) <= 45}) for combo in combos or []]
    final_combos = [combo for combo in final_combos if len(combo) == 6]
    if not final_combos:
        return "최종 추천번호가 없어 선택 근거를 분석하지 못했습니다."

    detail_map = _details_by_combo(details)
    aligned: List[Dict[str, Any]] = []
    for combo in final_combos:
        detail = dict(detail_map.get(tuple(combo), {}))
        detail["numbers"] = combo
        aligned.append(detail)

    evidence = _evidence_by_number(details)
    usage = Counter(n for combo in final_combos for n in combo)
    core = sorted(usage, key=lambda n: (-(usage[n] * 10 + _float(evidence.get(n, {}).get("selection_score"))), n))[:4]
    core_text = ", ".join(_reason(n, evidence, usage[n]) for n in core)
    line1 = f"[핵심수 선정] {core_text}"

    best_index = max(range(len(aligned)), key=lambda i: _float(aligned[i].get("score"), _float(aligned[i].get("display_score"))))
    best = aligned[best_index]
    best_combo = final_combos[best_index]
    ranked = sorted(best_combo, key=lambda n: -_float(evidence.get(n, {}).get("selection_score")))[:3]
    final_score = _float(best.get("display_score"), _float(best.get("score"), _float(best.get("ai_score"))))
    line2 = (
        f"[대표조합 선정] [{'-'.join(map(str, best_combo))}] · 최종점수 {final_score:.1f} · "
        f"주요 번호근거 {', '.join(_reason(n, evidence) for n in ranked)} · {_pair_basis(best)}"
    )

    odd = sum(n % 2 for n in best_combo)
    zones = [sum(n <= 15 for n in best_combo), sum(16 <= n <= 30 for n in best_combo), sum(n >= 31 for n in best_combo)]
    ac = _int(best.get("ac"))
    line3 = (
        f"[구조 필터] 합계 {sum(best_combo)} · 홀짝 {odd}:{6-odd} · "
        f"구간 {zones[0]}-{zones[1]}-{zones[2]} · AC {ac}"
    )

    overlaps = [len(set(a) & set(b)) for i, a in enumerate(final_combos) for b in final_combos[i + 1:]]
    sums = [sum(combo) for combo in final_combos]
    condition = ""
    if str(fixed or "").strip() or str(excluded or "").strip():
        condition = " 고정수와 제외수 조건도 최종 조합에 적용했습니다."
    line4 = (
        f"[중복·분산 보정] {len(final_combos)}조합 · 사용번호 {len(usage)}개 · "
        f"조합 간 최대중복 {max(overlaps, default=0)}개 · 합계범위 {min(sums)}~{max(sums)}.{condition}"
    )
    return "\n".join([line1, line2, line3, line4])


def build_evidence_analysis(round_no, stats, mode, fixed, excluded, details=None, combos=None) -> str:
    source_details = list(details or [])
    source_combos = combos or [_numbers(item) for item in source_details]
    return build_professional_analysis(round_no, stats or {}, mode, fixed, excluded, source_combos, source_details)


def build_recommendation_analysis(round_no, details=None, combos=None) -> str:
    return build_evidence_analysis(round_no, {}, "balanced", None, None, details or [], combos)


__all__ = ["build_professional_analysis", "build_evidence_analysis", "build_recommendation_analysis"]
