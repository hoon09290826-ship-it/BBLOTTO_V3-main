from __future__ import annotations

import hashlib
import secrets
from collections import Counter, deque
from typing import Any, Dict, Iterable, List, Mapping, Sequence

EXPLANATION_ENGINE_VERSION = "BBLOTTO_AI_EXPLANATION_RC1_GROUNDED_20260715"
_RNG = secrets.SystemRandom()
_RECENT_TEMPLATE_IDS: deque[str] = deque(maxlen=12)


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


def _choose(group: str, options: Sequence[str], seed_text: str) -> str:
    values = [x for x in options if x]
    if not values:
        return ""
    digest = hashlib.sha256(f"{group}|{seed_text}|{secrets.token_hex(4)}".encode()).hexdigest()
    start = int(digest[:8], 16) % len(values)
    for offset in range(len(values)):
        idx = (start + offset) % len(values)
        key = f"{group}:{idx}"
        if key not in _RECENT_TEMPLATE_IDS:
            _RECENT_TEMPLATE_IDS.append(key)
            return values[idx]
    idx = _RNG.randrange(len(values))
    _RECENT_TEMPLATE_IDS.append(f"{group}:{idx}")
    return values[idx]


def _numbers(source: Mapping[str, Any]) -> List[int]:
    raw = source.get("numbers") or source.get("nums") or source.get("combo") or []
    if not isinstance(raw, (list, tuple, set)):
        return []
    result: List[int] = []
    for value in raw:
        n = _i(value, -1)
        if 1 <= n <= 45 and n not in result:
            result.append(n)
    return sorted(result) if len(result) == 6 else []


def _valid_details(details: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for source in details or []:
        if not isinstance(source, Mapping):
            continue
        nums = _numbers(source)
        if nums:
            item = dict(source)
            item["numbers"] = nums
            out.append(item)
    return out


def _evidence_map(details: Sequence[Mapping[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for detail in details:
        for ev in detail.get("number_evidence") or []:
            if isinstance(ev, Mapping):
                n = _i(ev.get("number"), -1)
                if 1 <= n <= 45:
                    out[n] = dict(ev)
    return out


def _factor_phrases(ev: Mapping[str, Any]) -> List[str]:
    phrases: List[str] = []
    hot_rank = _i(ev.get("hot_rank"), 999)
    overdue_rank = _i(ev.get("overdue_rank"), 999)
    cold_rank = _i(ev.get("cold_rank"), 999)
    momentum = _f(ev.get("momentum"))
    gap = _i(ev.get("gap"))
    f10, f30, f100 = _i(ev.get("freq10")), _i(ev.get("freq30")), _i(ev.get("freq100"))
    if hot_rank <= 15:
        phrases.append(f"HOT {hot_rank}위")
    if momentum > 0.04:
        phrases.append(f"상승 모멘텀 +{momentum:.3f}")
    if overdue_rank <= 15 or gap >= 7:
        phrases.append(f"{gap}회 미출현 반등")
    if cold_rank <= 12:
        phrases.append(f"COLD {cold_rank}위 보강")
    if f10 or f30:
        phrases.append(f"최근 10회 {f10}회·30회 {f30}회 출현")
    if f100:
        phrases.append(f"최근 100회 {f100}회")
    if not phrases:
        phrases.append(f"누적 평가 {_f(ev.get('base_score')):.1f}")
    return phrases


def _number_reason(n: int, ev: Mapping[str, Any], usage: int | None = None) -> str:
    role = str(ev.get("role") or "균형수")
    factors = _factor_phrases(ev)[:2]
    use_text = f", {usage}개 조합 사용" if usage is not None else ""
    return f"{n}번({role}, {'·'.join(factors)}, 가중치 {_f(ev.get('selection_score')):.1f}{use_text})"


def _metrics(detail: Mapping[str, Any]) -> Dict[str, Any]:
    nums = detail["numbers"]
    odd = _i(detail.get("odd"), sum(n % 2 for n in nums))
    zones = detail.get("zones")
    if not isinstance(zones, (list, tuple)) or len(zones) != 3:
        zones = [sum(n <= 15 for n in nums), sum(16 <= n <= 30 for n in nums), sum(n >= 31 for n in nums)]
    return {
        "sum": _i(detail.get("sum"), sum(nums)), "odd": odd, "even": 6 - odd,
        "zones": [_i(x) for x in zones], "ac": _i(detail.get("ac")),
        "pair": _f(detail.get("pair_strength")), "score": _f(detail.get("score")),
        "base": _f(detail.get("base_score"), _f(detail.get("score"))),
        "repeat_penalty": _f(detail.get("diversity_penalty")),
        "overlap_penalty": _f(detail.get("overlap_penalty")),
        "type": str(detail.get("type") or "균형형"),
    }


def _pair_text(detail: Mapping[str, Any]) -> str:
    combo_ev = detail.get("combo_evidence") or {}
    pairs = combo_ev.get("pair_highlights") or []
    if pairs and isinstance(pairs[0], Mapping):
        nums = pairs[0].get("numbers") or []
        if len(nums) == 2:
            return f"{nums[0]}-{nums[1]} 동반출현 근거"
    return f"동반출현 점수 {_f(detail.get('pair_strength')):.1f}"


def _alternative_text(best: Mapping[str, Any], evidence: Mapping[int, Mapping[str, Any]]) -> str:
    alt = best.get("alternative_candidate")
    if not isinstance(alt, Mapping):
        return ""
    kept = _i(alt.get("kept_number"), -1)
    replaced = _i(alt.get("replaced_candidate"), -1)
    advantage = _f(alt.get("score_advantage"))
    if not (1 <= kept <= 45 and 1 <= replaced <= 45):
        return ""
    kept_reason = _number_reason(kept, evidence.get(kept, {}))
    if advantage >= 0:
        return f"5개 번호가 같은 대체 후보의 {replaced}번보다 {kept_reason}이 기본평가에서 {advantage:.1f}점 앞서 최종 유지됐습니다."
    return f"대체 후보 {replaced}번이 기본점수는 {-advantage:.1f}점 높았지만, 번호 반복과 조합 편중을 줄이기 위해 {kept_reason}을 유지했습니다."


def build_round_analysis(round_no: int, stats: Mapping[str, Any] | None, mode: str, fixed: Any, excluded: Any, details: Sequence[Mapping[str, Any]]) -> str:
    valid = _valid_details(details)
    if not valid:
        return "추천 조합의 실제 선택 근거가 없어 분석 문구를 생성하지 못했습니다."

    evidence = _evidence_map(valid)
    usage = Counter(n for d in valid for n in d["numbers"])
    seed = f"{round_no}|{mode}|" + ";".join("-".join(map(str, d["numbers"])) for d in valid)

    core = sorted(usage, key=lambda n: (-(usage[n] * 12 + _f(evidence.get(n, {}).get("selection_score"))), n))[:3]
    core_text = ", ".join(_number_reason(n, evidence.get(n, {}), usage[n]) for n in core)
    line1 = _choose("core", [
        f"{round_no}회차는 실제 번호별 평가와 사용 횟수를 대조해 {core_text}을 핵심 축으로 잡았습니다.",
        f"이번 추천의 중심은 {core_text}이며, 최근 흐름·미출현 간격·최종 가중치를 함께 반영한 결과입니다.",
        f"생성된 {len(valid)}개 조합에서 반복 채택된 핵심 번호는 {core_text}으로, 단순 반복이 아니라 실제 평가값을 기준으로 배치했습니다.",
        f"번호별 점수표와 조합 사용 빈도를 함께 비교한 결과 {core_text}이 이번 회차의 주축으로 선별됐습니다.",
        f"이번 번호 구성은 {core_text}을 중심으로 만들고, 나머지 번호는 구간과 중복 분산을 맞추는 방식으로 채웠습니다.",
        f"핵심수 선정에서는 사용 횟수와 선택 가중치를 함께 보았고, 그 결과 {core_text}이 우선 배치됐습니다.",
    ], seed)

    best = max(valid, key=lambda d: _f(d.get("score")))
    m = _metrics(best)
    combo = "-".join(map(str, best["numbers"]))
    ranked_nums = sorted(best["numbers"], key=lambda n: -_f(evidence.get(n, {}).get("selection_score")))[:3]
    reasons = ", ".join(_number_reason(n, evidence.get(n, {})) for n in ranked_nums)
    pair_basis = _pair_text(best)
    line2 = _choose("best", [
        f"대표 조합 [{combo}]은 {reasons}의 평가가 가장 크게 작용했고, {pair_basis}까지 더해져 {m['type']}으로 선별됐습니다.",
        f"최고점 조합 [{combo}]에서는 {reasons}이 직접적인 채택 근거였으며, {pair_basis}가 조합 점수를 보강했습니다.",
        f"[{combo}]이 대표 조합이 된 이유는 {reasons}을 한 조합에 결합하면서 {pair_basis}와 구조 조건을 함께 통과했기 때문입니다.",
        f"후보 비교 결과 [{combo}]은 {reasons}을 포함했고, {pair_basis}까지 확보해 포트폴리오 점수 {m['score']:.1f}점으로 올라섰습니다.",
        f"실제 후보군 가운데 [{combo}]은 번호 가중치가 높은 {reasons}과 {pair_basis}가 동시에 확인돼 최종 대표 조합이 됐습니다.",
        f"대표 조합 [{combo}]은 핵심 번호인 {reasons}을 포함하면서 {pair_basis}도 확보해 다른 후보보다 조합 완성도가 높았습니다.",
    ], seed)

    alt = _alternative_text(best, evidence)
    penalties: List[str] = []
    if m["repeat_penalty"] > 0:
        penalties.append(f"번호 반복 감점 {m['repeat_penalty']:.1f}")
    if m["overlap_penalty"] > 0:
        penalties.append(f"조합 중복 감점 {m['overlap_penalty']:.1f}")
    penalty_text = "·".join(penalties) if penalties else "추가 감점 없이"
    structure = f"홀짝 {m['odd']}:{m['even']}·구간 {m['zones'][0]}-{m['zones'][1]}-{m['zones'][2]}·합계 {m['sum']}·AC {m['ac']}·동반출현 {m['pair']:.1f}"
    line3 = _choose("structure", [
        f"{alt} 구조 검증은 {structure}였고, {penalty_text} 기본점수 {m['base']:.1f}점이 최종 {m['score']:.1f}점으로 확정됐습니다.",
        f"{alt} 최종 선별 단계에서는 {structure}를 확인했으며, {penalty_text} 포트폴리오 점수 {m['score']:.1f}점을 기록했습니다.",
        f"{alt} 이 조합은 {structure} 조건을 통과했고, {penalty_text} 최종 평가를 마쳤습니다.",
        f"{alt} 번호 선택 뒤에는 {structure}를 다시 검사했고, {penalty_text} 최종점수 {m['score']:.1f}점으로 남았습니다.",
        f"{alt} 조합 구조는 {structure}로 정리됐으며, {penalty_text} 기본평가와 포트폴리오 평가를 모두 통과했습니다.",
        f"{alt} 마지막 검증에서 {structure}가 확인됐고, {penalty_text} 최종 후보로 확정했습니다.",
    ], seed)

    combos = [d["numbers"] for d in valid]
    sums = [sum(c) for c in combos]
    overlaps = [len(set(a) & set(b)) for i, a in enumerate(combos) for b in combos[i+1:]]
    unique_count, max_use, max_overlap = len(usage), max(usage.values(), default=0), max(overlaps, default=0)
    condition = ""
    if str(fixed or "").strip() or str(excluded or "").strip():
        condition = " 입력한 고정수와 제외수 조건도 모든 조합에 그대로 적용했습니다."
    line4 = _choose("portfolio", [
        f"전체 {len(combos)}개 조합은 {unique_count}개 번호를 활용하고 한 번호 최대 {max_use}회, 조합 간 최대 중복 {max_overlap}개, 합계 {min(sums)}~{max(sums)}로 분산했습니다.{condition}",
        f"포트폴리오 전체는 사용 번호 {unique_count}개·최대 반복 {max_use}회·최대 겹침 {max_overlap}개로 관리했고, 합계도 {min(sums)}~{max(sums)} 범위로 나눴습니다.{condition}",
        f"마지막으로 {len(combos)}개 조합을 함께 비교해 {unique_count}개 번호로 분산하고, 특정 번호는 최대 {max_use}회까지만 사용했으며 겹침은 최대 {max_overlap}개로 제한했습니다.{condition}",
        f"개별 점수뿐 아니라 전체 묶음의 균형도 확인해 합계 {min(sums)}~{max(sums)}, 사용 번호 {unique_count}개, 최대 반복 {max_use}회로 최종 배치했습니다.{condition}",
        f"전체 조합은 번호 {unique_count}개를 분산 활용했고, 최대 사용 {max_use}회와 조합 간 최대 중복 {max_overlap}개를 넘지 않도록 조정했습니다.{condition}",
        f"최종 묶음은 합계 {min(sums)}~{max(sums)} 범위, 사용 번호 {unique_count}개, 한 번호 최대 {max_use}회로 구성해 한쪽 패턴에 몰리지 않게 했습니다.{condition}",
    ], seed)

    return "\n".join([line1, line2, line3, line4])
