"""BBLOTTO recommendation explanation engine.

This module is the single owner of member-facing analysis text.  Number
generation code supplies final combinations and evidence; this module explains
why visible numbers were selected without generating or changing numbers.
"""
from __future__ import annotations

import secrets
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Sequence


_LAST_TEMPLATE: Dict[str, int] = {}


def _pick(group: str, options: Sequence[str]) -> str:
    """Avoid using the same sentence structure on consecutive generations."""
    if not options:
        return ""
    candidates = [i for i in range(len(options)) if i != _LAST_TEMPLATE.get(group)]
    index = candidates[secrets.randbelow(len(candidates))] if candidates else 0
    _LAST_TEMPLATE[group] = index
    return options[index]


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
    line1 = _pick("core", [
        f"번호별 선택평가에서는 {core_text}가 이번 회차 핵심 후보로 선별됐습니다.",
        f"최근 출현 흐름과 번호 가중치를 대조한 결과 핵심수는 {core_text}입니다.",
        f"AI 후보군의 순위·미출현 간격·선택 가중치를 종합하면 {core_text}가 중심축입니다.",
        f"최종 번호별 평가에서 우선 반영된 후보는 {core_text}로 확인됐습니다.",
        f"이번 조합에 반복 채택된 핵심 번호와 직접 근거는 {core_text}입니다.",
    ])

    best_index = max(range(len(aligned)), key=lambda i: _float(aligned[i].get("score"), _float(aligned[i].get("display_score"))))
    best = aligned[best_index]
    best_combo = final_combos[best_index]
    ranked = sorted(best_combo, key=lambda n: -_float(evidence.get(n, {}).get("selection_score")))[:3]
    final_score = _float(best.get("display_score"), _float(best.get("score"), _float(best.get("ai_score"))))
    combo_text = f"[{'-'.join(map(str, best_combo))}]"
    ranked_text = ", ".join(_reason(n, evidence) for n in ranked)
    pair_text = _pair_basis(best)
    line2 = _pick("representative", [
        f"대표 조합 {combo_text}은 최종점수 {final_score:.1f}점으로, {ranked_text}의 개별 근거와 {pair_text}가 함께 작용했습니다.",
        f"후보 조합 비교 결과 {combo_text}이 {final_score:.1f}점으로 선별됐으며 핵심 근거는 {ranked_text}, {pair_text}입니다.",
        f"{combo_text}은 번호 가중치가 높은 {ranked_text}와 {pair_text}를 결합해 최종평가 {final_score:.1f}점을 기록했습니다.",
        f"최종 대표 조합은 {combo_text}이며, {ranked_text}의 선택평가와 {pair_text}를 반영한 점수는 {final_score:.1f}점입니다.",
        f"개별 번호 평가와 동반출현을 함께 계산했을 때 {combo_text}이 {final_score:.1f}점으로 남았고 주요 근거는 {ranked_text}, {pair_text}입니다.",
    ])

    odd = sum(n % 2 for n in best_combo)
    zones = [sum(n <= 15 for n in best_combo), sum(16 <= n <= 30 for n in best_combo), sum(n >= 31 for n in best_combo)]
    ac = _int(best.get("ac"))
    structure = f"합계 {sum(best_combo)}·홀짝 {odd}:{6-odd}·구간 {zones[0]}-{zones[1]}-{zones[2]}·AC {ac}"
    line3 = _pick("structure", [
        f"조합 구조 검증값은 {structure}이며 이 조건으로 최종 필터를 통과했습니다.",
        f"구조 필터에서는 {structure}를 확인해 번호대 편중과 조합 형태를 검증했습니다.",
        f"대표 조합의 구조지표는 {structure}로 계산됐고 후보 선별 조건에 반영됐습니다.",
        f"번호 구성 검증 결과 {structure}가 확인돼 구조 조건을 충족했습니다.",
        f"최종 구조평가에는 {structure}가 적용됐으며 합계·홀짝·구간·AC 조건을 모두 대조했습니다.",
    ])

    overlaps = [len(set(a) & set(b)) for i, a in enumerate(final_combos) for b in final_combos[i + 1:]]
    sums = [sum(combo) for combo in final_combos]
    condition = ""
    if str(fixed or "").strip() or str(excluded or "").strip():
        condition = " 고정수와 제외수 조건도 최종 조합에 적용했습니다."
    portfolio = (
        f"{len(final_combos)}조합·사용번호 {len(usage)}개·조합 간 최대중복 "
        f"{max(overlaps, default=0)}개·합계범위 {min(sums)}~{max(sums)}"
    )
    line4 = _pick("portfolio", [
        f"전체 포트폴리오는 {portfolio}로 중복과 번호 쏠림을 보정했습니다.{condition}",
        f"마지막 분산 단계에서 {portfolio}를 기준으로 유사 조합 반복을 제한했습니다.{condition}",
        f"조합 전체를 다시 비교해 {portfolio}가 되도록 번호 사용량과 중복을 조정했습니다.{condition}",
        f"최종 묶음은 {portfolio}로 구성해 개별 점수뿐 아니라 조합 간 분산까지 반영했습니다.{condition}",
        f"포트폴리오 보정 결과는 {portfolio}이며 동일 번호와 유사 패턴의 과다 반복을 줄였습니다.{condition}",
    ])
    return "\n".join([line1, line2, line3, line4])


def build_evidence_analysis(round_no, stats, mode, fixed, excluded, details=None, combos=None) -> str:
    source_details = list(details or [])
    source_combos = combos or [_numbers(item) for item in source_details]
    return build_professional_analysis(round_no, stats or {}, mode, fixed, excluded, source_combos, source_details)


def build_recommendation_analysis(round_no, details=None, combos=None) -> str:
    return build_evidence_analysis(round_no, {}, "balanced", None, None, details or [], combos)


__all__ = ["build_professional_analysis", "build_evidence_analysis", "build_recommendation_analysis"]
