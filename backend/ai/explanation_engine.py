from __future__ import annotations

import secrets
import statistics
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .cache_engine import get_analysis_cache

EXPLANATION_ENGINE_VERSION = "BBLOTTO_AI_EXPLANATION_V14_GROUNDED_DYNAMIC"
_RNG = secrets.SystemRandom()


def _i(v: Any, d: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _choose(items: Sequence[str]) -> str:
    return _RNG.choice(list(items)) if items else ""


def _nums(detail: Mapping[str, Any]) -> List[int]:
    raw = detail.get("numbers") or detail.get("nums") or detail.get("combo") or []
    out: List[int] = []
    if isinstance(raw, (list, tuple, set)):
        for v in raw:
            n = _i(v, -1)
            if 1 <= n <= 45 and n not in out:
                out.append(n)
    return sorted(out) if len(out) == 6 else []


def _valid(details: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for src in details or []:
        if not isinstance(src, Mapping):
            continue
        nums = _nums(src)
        if nums:
            item = dict(src)
            item["numbers"] = nums
            out.append(item)
    return out


def _evidence_by_number(details: Sequence[Mapping[str, Any]]) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    for detail in details:
        for raw in detail.get("number_evidence") or []:
            if not isinstance(raw, Mapping):
                continue
            n = _i(raw.get("number"), -1)
            if 1 <= n <= 45:
                current = result.setdefault(n, {})
                for k, v in raw.items():
                    if k not in current or current[k] in (None, "", 0, []):
                        current[k] = v
    return result


def _reason_text(number: int, ev: Mapping[str, Any]) -> str:
    role = str(ev.get("role") or "균형수")
    f10 = _i(ev.get("freq10"))
    f30 = _i(ev.get("freq30"))
    f100 = _i(ev.get("freq100"))
    gap = _i(ev.get("gap"))
    score = _f(ev.get("selection_score"))
    given = str(ev.get("reason") or "").strip()

    if role == "반등수" or gap >= 8:
        options = [
            f"{number}번은 최근 {gap}회 동안 나오지 않은 공백을 반등 신호로 반영한 번호",
            f"{number}번은 미출현 간격 {gap}회를 보완하기 위해 일부 조합에 배치한 반등 후보",
        ]
    elif role == "강세수" or f10 >= 2 or f30 >= 5:
        options = [
            f"{number}번은 최근 10회 {f10}회·30회 {f30}회 출현한 흐름을 반영한 강세 후보",
            f"{number}번은 단기 {f10}회, 중기 {f30}회의 출현 흐름이 이어져 중심축으로 채택한 번호",
        ]
    else:
        options = [
            f"{number}번은 최근 100회 {f100}회 출현과 선택점수 {score:.1f}를 함께 본 균형 후보",
            f"{number}번은 단기 편중보다 누적 흐름과 선택점수 {score:.1f}가 안정적인 보완 번호",
        ]
    if given and not any(x in given for x in ("후보", "흐름", "출현")):
        options.append(f"{number}번은 {given}")
    return _choose(options)


def _combo_metrics(detail: Mapping[str, Any]) -> Dict[str, Any]:
    nums = detail["numbers"]
    odd = _i(detail.get("odd"), sum(n % 2 for n in nums))
    even = _i(detail.get("even"), 6 - odd)
    zones = detail.get("zones")
    if not isinstance(zones, (list, tuple)) or len(zones) != 3:
        zones = [sum(n <= 15 for n in nums), sum(16 <= n <= 30 for n in nums), sum(n >= 31 for n in nums)]
    return {
        "sum": _i(detail.get("sum"), sum(nums)),
        "odd": odd,
        "even": even,
        "zones": [_i(x) for x in zones],
        "ac": _i(detail.get("ac")),
        "pair": _f(detail.get("pair_strength")),
        "score": _f(detail.get("score")),
        "type": str(detail.get("type") or detail.get("strategy") or "균형형"),
    }


def _core_line(round_no: int, details: Sequence[Mapping[str, Any]], evidence: Mapping[int, Mapping[str, Any]]) -> str:
    usage = Counter(n for d in details for n in d["numbers"])
    ranked = sorted(usage, key=lambda n: (-usage[n], -_f(evidence.get(n, {}).get("selection_score")), n))[:4]
    pieces = [f"{_reason_text(n, evidence.get(n, {}))}로 {usage[n]}개 조합에 사용" for n in ranked]
    lead = _choose([
        f"{round_no}회차 추천번호는 실제 생성된 10개 조합의 사용 비중과 번호별 점수를 다시 확인해 구성했습니다.",
        f"이번 {round_no}회차는 생성된 조합 안에서 반복 사용된 번호와 각 번호의 출현 근거를 기준으로 핵심축을 정했습니다.",
        f"{round_no}회차 결과에서는 조합별 채택 빈도와 최근·누적 흐름을 함께 비교해 중심 번호를 선별했습니다.",
    ])
    return lead + " " + ", ".join(pieces) + "했습니다."


def _best_combo_line(details: Sequence[Mapping[str, Any]], evidence: Mapping[int, Mapping[str, Any]]) -> str:
    best = max(details, key=lambda d: _f(d.get("score")))
    nums = best["numbers"]
    m = _combo_metrics(best)
    # Explain three actual numbers from the selected combo, not generic portfolio text.
    selected = sorted(nums, key=lambda n: (-_f(evidence.get(n, {}).get("selection_score")), n))[:3]
    why = "; ".join(_reason_text(n, evidence.get(n, {})) for n in selected)
    combo = "-".join(map(str, nums))
    intro = _choose([
        f"최고 평가 조합 [{combo}]은 {why}라는 실제 채택 근거로 구성됐습니다.",
        f"[{combo}] 조합은 {why}를 한 조합 안에서 결합한 결과 가장 높은 평가를 받았습니다.",
        f"대표 조합 [{combo}]에서는 {why}를 핵심 선택 근거로 사용했습니다.",
    ])
    tail = _choose([
        f"홀짝 {m['odd']}:{m['even']}, 구간 {m['zones'][0]}-{m['zones'][1]}-{m['zones'][2]}, 합계 {m['sum']}, AC {m['ac']}, 동반출현 {m['pair']:.1f} 조건을 통과했습니다.",
        f"최종 구조는 합계 {m['sum']}·홀짝 {m['odd']}:{m['even']}·구간 {m['zones'][0]}-{m['zones'][1]}-{m['zones'][2]}이며 AC {m['ac']}와 동반출현 점수 {m['pair']:.1f}를 만족했습니다.",
    ])
    return intro + " " + tail


def _portfolio_line(details: Sequence[Mapping[str, Any]]) -> str:
    combos = [d["numbers"] for d in details]
    usage = Counter(n for c in combos for n in c)
    sums = [sum(c) for c in combos]
    overlaps = [len(set(a) & set(b)) for i, a in enumerate(combos) for b in combos[i + 1 :]]
    max_overlap = max(overlaps, default=0)
    max_use = max(usage.values(), default=0)
    unique = len(usage)
    median_sum = round(statistics.median(sums))
    return _choose([
        f"전체 {len(combos)}개 조합은 {unique}개 번호로 분산했고, 한 번호의 최대 사용은 {max_use}회, 조합 간 최대 중복은 {max_overlap}개로 제한했습니다. 합계는 {min(sums)}~{max(sums)} 범위이며 중앙값은 {median_sum}입니다.",
        f"번호 편중을 줄이기 위해 {unique}개 번호를 나눠 사용했으며 최대 반복 {max_use}회, 조합 간 최대 겹침 {max_overlap}개를 넘지 않도록 정리했습니다. 조합 합계는 {min(sums)}~{max(sums)}로 분산됐습니다.",
        f"포트폴리오 단계에서는 총 {unique}개 번호를 활용하고 동일 번호는 최대 {max_use}개 조합까지만 사용했습니다. 조합끼리 겹치는 번호도 최대 {max_overlap}개로 제한하고 합계 중앙값을 {median_sum}으로 맞췄습니다.",
    ])


def _condition_line(fixed: Any, excluded: Any) -> str:
    parts: List[str] = []
    if str(fixed or "").strip():
        parts.append("입력한 고정수는 모든 조합에 유지")
    if str(excluded or "").strip():
        parts.append("제외수는 후보 계산과 최종 조합에서 배제")
    return "사용자 조건은 " + ", ".join(parts) + "했습니다." if parts else ""


def build_round_analysis(
    round_no: int,
    stats: Mapping[str, Any] | None,
    mode: str,
    fixed: Any,
    excluded: Any,
    details: Sequence[Mapping[str, Any]],
) -> str:
    valid = _valid(details)
    if not valid:
        return "추천 조합의 실제 번호 데이터가 없어 설명을 생성하지 못했습니다. 번호를 다시 생성해 주세요."

    evidence = _evidence_by_number(valid)
    lines = [
        _core_line(_i(round_no), valid, evidence),
        _best_combo_line(valid, evidence),
        _portfolio_line(valid),
    ]
    condition = _condition_line(fixed, excluded)
    if condition:
        lines.append(condition)

    # Change presentation order on every generation while keeping the factual
    # core-number line first so the explanation remains easy to read.
    tail = lines[1:]
    _RNG.shuffle(tail)
    return "\n".join([lines[0], *tail][:5])
