from __future__ import annotations

import secrets
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Sequence

EXPLANATION_ENGINE_VERSION = "BBLOTTO_AI_EXPLANATION_V16_GROUNDED_DYNAMIC"
_RNG = secrets.SystemRandom()


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pick(options: Sequence[str]) -> str:
    values = [x for x in options if x]
    return _RNG.choice(values) if values else ""


def _numbers(source: Mapping[str, Any]) -> List[int]:
    raw = source.get("numbers") or source.get("nums") or source.get("combo") or []
    if not isinstance(raw, (list, tuple, set)):
        return []
    result: List[int] = []
    for value in raw:
        number = _i(value, -1)
        if 1 <= number <= 45 and number not in result:
            result.append(number)
    return sorted(result) if len(result) == 6 else []


def _valid_details(details: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for source in details or []:
        if not isinstance(source, Mapping):
            continue
        nums = _numbers(source)
        if nums:
            item = dict(source)
            item["numbers"] = nums
            result.append(item)
    return result


def _evidence_map(details: Sequence[Mapping[str, Any]]) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    for detail in details:
        for evidence in detail.get("number_evidence") or []:
            if not isinstance(evidence, Mapping):
                continue
            number = _i(evidence.get("number"), -1)
            if 1 <= number <= 45:
                result[number] = dict(evidence)
    return result


def _number_reason(number: int, evidence: Mapping[str, Any]) -> str:
    factors = evidence.get("factors") or []
    factor_texts = [
        str(item.get("text"))
        for item in factors
        if isinstance(item, Mapping) and item.get("text")
    ]
    if factor_texts:
        basis = "·".join(factor_texts[:2])
    else:
        basis = (
            f"최근 10회 {_i(evidence.get('freq10'))}회, "
            f"30회 {_i(evidence.get('freq30'))}회, "
            f"미출현 {_i(evidence.get('gap'))}회"
        )
    role = str(evidence.get("role") or "균형수")
    score = _f(evidence.get("selection_score"))
    return f"{number}번({role}, {basis}, 가중치 {score:.1f})"


def _metrics(detail: Mapping[str, Any]) -> Dict[str, Any]:
    nums = detail["numbers"]
    odd = _i(detail.get("odd"), sum(n % 2 for n in nums))
    zones = detail.get("zones")
    if not isinstance(zones, (list, tuple)) or len(zones) != 3:
        zones = [
            sum(n <= 15 for n in nums),
            sum(16 <= n <= 30 for n in nums),
            sum(n >= 31 for n in nums),
        ]
    return {
        "sum": _i(detail.get("sum"), sum(nums)),
        "odd": odd,
        "even": _i(detail.get("even"), 6 - odd),
        "zones": [_i(x) for x in zones],
        "ac": _i(detail.get("ac")),
        "pair": _f(detail.get("pair_strength")),
        "score": _f(detail.get("score")),
        "base": _f(detail.get("base_score"), _f(detail.get("score"))),
        "diversity_penalty": _f(detail.get("diversity_penalty")),
        "overlap_penalty": _f(detail.get("overlap_penalty")),
        "type": str(detail.get("type") or "균형형"),
    }


def _alternative_sentence(best: Mapping[str, Any], evidence: Mapping[int, Mapping[str, Any]]) -> str:
    alt = best.get("alternative_candidate")
    if not isinstance(alt, Mapping):
        return ""
    kept = _i(alt.get("kept_number"), -1)
    replaced = _i(alt.get("replaced_candidate"), -1)
    advantage = _f(alt.get("score_advantage"))
    if not (1 <= kept <= 45 and 1 <= replaced <= 45):
        return ""
    kept_ev = evidence.get(kept, {})
    kept_reason = _number_reason(kept, kept_ev)
    if advantage >= 0:
        return _pick([
            f"가까운 대체 후보의 {replaced}번 대신 {kept_reason}을 유지했으며, 기본점수도 {advantage:.1f}점 앞섰습니다.",
            f"5개 번호가 같은 후보와 비교했을 때 {replaced}번을 빼고 {kept_reason}을 채택해 기본평가에서 {advantage:.1f}점 우위를 확보했습니다.",
            f"대체 후보 {replaced}번보다 {kept_reason}의 실제 가중치와 조합 적합도가 높아 최종 조합에 남았습니다(기본점수 차이 {advantage:.1f}점).",
        ])
    return _pick([
        f"기본점수만 보면 대체 후보가 {-advantage:.1f}점 높았지만, {kept_reason}을 유지해 전체 조합의 번호 반복과 패턴 편중을 줄였습니다.",
        f"대체 후보 {replaced}번이 기본평가에서 {-advantage:.1f}점 앞섰으나, 포트폴리오 분산을 위해 {kept_reason}을 최종 선택했습니다.",
    ])


def build_round_analysis(
    round_no: int,
    stats: Mapping[str, Any] | None,
    mode: str,
    fixed: Any,
    excluded: Any,
    details: Sequence[Mapping[str, Any]],
) -> str:
    valid = _valid_details(details)
    if not valid:
        return "추천 조합의 실제 선택 근거가 없어 분석 문구를 생성하지 못했습니다."

    evidence = _evidence_map(valid)
    usage = Counter(number for detail in valid for number in detail["numbers"])
    core = sorted(
        usage,
        key=lambda n: (-(usage[n] * 10 + _f(evidence.get(n, {}).get("selection_score"))), n),
    )[:3]
    core_text = ", ".join(
        f"{_number_reason(number, evidence.get(number, {}))}을 {usage[number]}개 조합에 사용"
        for number in core
    )
    line1 = _pick([
        f"{round_no}회차는 실제 가중치와 채택 횟수를 대조해 {core_text}하며 핵심 축을 구성했습니다.",
        f"생성된 조합에서 반복 사용된 중심 번호는 {core_text}한 결과이며, 단순 무작위 반복이 아니라 번호별 평가값을 반영했습니다.",
        f"번호별 최근 흐름·미출현 간격·최종 가중치를 비교한 결과 {core_text}해 이번 포트폴리오의 중심으로 삼았습니다.",
        f"이번 추천은 실제 번호 평가표를 기준으로 {core_text}했고, 나머지 번호는 구간과 중복 분산을 맞추도록 배치했습니다.",
    ])

    best = max(valid, key=lambda item: _f(item.get("score")))
    metrics = _metrics(best)
    combo = "-".join(map(str, best["numbers"]))
    top_numbers = sorted(
        best["numbers"],
        key=lambda n: -_f(evidence.get(n, {}).get("selection_score")),
    )[:3]
    direct_reasons = ", ".join(_number_reason(n, evidence.get(n, {})) for n in top_numbers)
    line2 = _pick([
        f"대표 조합 [{combo}]은 {direct_reasons}의 평가가 가장 크게 작용해 {metrics['type']}으로 선별됐습니다.",
        f"최고점 조합 [{combo}]에서는 {direct_reasons}이 직접적인 채택 근거였고, 최종 포트폴리오 점수는 {metrics['score']:.1f}점입니다.",
        f"[{combo}]이 대표 조합이 된 이유는 {direct_reasons}을 한 조합에 결합하면서도 구조 조건을 통과했기 때문입니다.",
        f"실제 후보 비교에서 [{combo}]은 {direct_reasons}을 포함해 번호 가중치와 조합 적합도를 동시에 확보했습니다.",
    ])

    alternative = _alternative_sentence(best, evidence)
    penalty_parts: List[str] = []
    if metrics["diversity_penalty"] > 0:
        penalty_parts.append(f"번호 반복 감점 {metrics['diversity_penalty']:.1f}")
    if metrics["overlap_penalty"] > 0:
        penalty_parts.append(f"조합 중복 감점 {metrics['overlap_penalty']:.1f}")
    penalty_text = "·".join(penalty_parts) if penalty_parts else "추가 반복 감점 없이"
    structure = (
        f"홀짝 {metrics['odd']}:{metrics['even']}, 구간 "
        f"{metrics['zones'][0]}-{metrics['zones'][1]}-{metrics['zones'][2]}, "
        f"합계 {metrics['sum']}, AC {metrics['ac']}, 동반출현 {metrics['pair']:.1f}"
    )
    line3 = _pick([
        f"{alternative} 구조 검증은 {structure}였고, {penalty_text} 최종점수 {metrics['score']:.1f}점으로 확정했습니다.",
        f"{alternative} 또한 {structure} 조건을 확인했으며, {penalty_text} 기본점수 {metrics['base']:.1f}점을 포트폴리오 점수 {metrics['score']:.1f}점으로 조정했습니다.",
        f"{alternative} 최종 선별 단계에서는 {structure}를 함께 검사하고 {penalty_text} 평가를 마쳤습니다.",
    ])

    combos = [detail["numbers"] for detail in valid]
    sums = [sum(combo_numbers) for combo_numbers in combos]
    overlaps = [
        len(set(left) & set(right))
        for index, left in enumerate(combos)
        for right in combos[index + 1 :]
    ]
    unique_count = len(usage)
    max_use = max(usage.values(), default=0)
    max_overlap = max(overlaps, default=0)
    line4 = _pick([
        f"전체 {len(combos)}개 조합은 {unique_count}개 번호를 활용하고 한 번호 최대 {max_use}회, 조합 간 최대 중복 {max_overlap}개, 합계 {min(sums)}~{max(sums)}로 분산해 한 패턴에 몰리지 않도록 구성했습니다.",
        f"포트폴리오 전체는 사용 번호 {unique_count}개·최대 반복 {max_use}회·최대 겹침 {max_overlap}개로 관리했고, 조합 합계도 {min(sums)}~{max(sums)} 범위로 나눴습니다.",
        f"마지막으로 {len(combos)}개 조합을 함께 비교해 {unique_count}개 번호로 분산하고, 특정 번호는 최대 {max_use}회까지만 사용했으며 조합 간 겹침은 최대 {max_overlap}개로 제한했습니다.",
        f"개별 조합 점수뿐 아니라 전체 묶음의 균형도 확인해 합계 범위 {min(sums)}~{max(sums)}, 사용 번호 {unique_count}개, 최대 반복 {max_use}회로 최종 배치했습니다.",
    ])
    if str(fixed or "").strip() or str(excluded or "").strip():
        line4 += " 입력한 고정수와 제외수 조건도 최종 조합에 그대로 적용했습니다."

    return "\n".join([line1, line2, line3, line4])
