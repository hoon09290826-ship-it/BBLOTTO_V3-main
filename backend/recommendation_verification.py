from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Sequence


VERIFICATION_VERSION = "BBLOTTO_RECOMMENDATION_PROOF_V1_20260721"


def _numbers(value: Any) -> List[int]:
    if not isinstance(value, (list, tuple)):
        return []
    result: List[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 45 and number not in result:
            result.append(number)
    return sorted(result)


def _number_set(value: Any) -> set[int]:
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    return set(_numbers(value if isinstance(value, (list, tuple)) else []))


def _compact_evidence(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    output: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        output.append({
            "number": int(item.get("number") or 0),
            "role": str(item.get("role") or ""),
            "selection_score": item.get("selection_score"),
            "freq10": item.get("freq10"),
            "freq30": item.get("freq30"),
            "freq100": item.get("freq100"),
            "gap": item.get("gap"),
            "momentum": item.get("momentum"),
            "hot_rank": item.get("hot_rank"),
            "overdue_rank": item.get("overdue_rank"),
            "factors": [
                str(factor.get("code") or "")
                for factor in (item.get("factors") or [])
                if isinstance(factor, dict)
            ],
        })
    return output


def build_generation_verification(
    *,
    round_no: int,
    mode: str,
    member_grade: str,
    fixed: Any,
    excluded: Any,
    combos: Sequence[Sequence[int]],
    details: Sequence[Dict[str, Any]],
    stats: Dict[str, Any],
    engine: Dict[str, Any],
) -> Dict[str, Any]:
    """최종 추천번호를 변경하지 않고 분석 근거와 일치 여부만 검증한다."""
    normalized = [_numbers(combo) for combo in combos]
    fixed_set = _number_set(fixed)
    excluded_set = _number_set(excluded)
    detail_rows = list(details or [])
    combo_proofs: List[Dict[str, Any]] = []
    aligned = len(normalized) == len(detail_rows)
    evidence_complete = True

    for index, combo in enumerate(normalized):
        detail = (
            detail_rows[index]
            if index < len(detail_rows) and isinstance(detail_rows[index], dict)
            else {}
        )
        detail_numbers = _numbers(detail.get("numbers"))
        evidence = _compact_evidence(detail.get("number_evidence"))
        evidence_numbers = sorted(
            int(row.get("number") or 0)
            for row in evidence
            if row.get("number")
        )
        row_aligned = combo == detail_numbers
        row_evidence = combo == evidence_numbers and len(evidence) == 6
        aligned = aligned and row_aligned
        evidence_complete = evidence_complete and row_evidence
        trace = (
            detail.get("selection_trace")
            if isinstance(detail.get("selection_trace"), dict)
            else {}
        )
        combo_proofs.append({
            "index": index + 1,
            "numbers": combo,
            "detail_aligned": row_aligned,
            "evidence_complete": row_evidence,
            "candidate_rank": detail.get("candidate_rank") or trace.get("candidate_rank"),
            "selection_rank": detail.get("selection_rank") or index + 1,
            "strategy": str(detail.get("strategy") or detail.get("type") or ""),
            "base_score": detail.get("base_score"),
            "raw_score": detail.get("raw_score") or detail.get("score"),
            "display_score": detail.get("display_score"),
            "strategy_bonus": detail.get("strategy_bonus") or trace.get("strategy_bonus"),
            "portfolio_adjustment": detail.get("portfolio_adjustment"),
            "repeat_penalty": detail.get("diversity_penalty") or trace.get("number_repeat_penalty"),
            "overlap_penalty": detail.get("overlap_penalty") or trace.get("combo_overlap_penalty"),
            "max_previous_overlap": detail.get("max_previous_overlap") or trace.get("max_previous_overlap"),
            "ensemble_version": detail.get("ensemble_version"),
            "ensemble_score": detail.get("ensemble_score"),
            "ensemble_votes": detail.get("ensemble_votes"),
            "ensemble_candidate_rank": detail.get("ensemble_candidate_rank"),
            "ensemble_components": detail.get("ensemble_components") or {},
            "number_evidence": evidence,
        })

    validations = {
        "six_unique_numbers": bool(normalized)
        and all(len(combo) == 6 and len(set(combo)) == 6 for combo in normalized),
        "numbers_in_range": all(
            all(1 <= number <= 45 for number in combo) for combo in normalized
        ),
        "no_duplicate_combinations": len({tuple(combo) for combo in normalized})
        == len(normalized),
        "fixed_numbers_included": all(
            fixed_set.issubset(set(combo)) for combo in normalized
        ),
        "excluded_numbers_absent": all(
            not (excluded_set & set(combo)) for combo in normalized
        ),
        "details_match_final_numbers": aligned,
        "six_number_evidence_rows": evidence_complete,
        "ensemble_trace_complete": bool(normalized) and all(
            isinstance(detail_rows[index].get("ensemble_components"), dict)
            and len(detail_rows[index].get("ensemble_components") or {}) == 5
            and detail_rows[index].get("ensemble_score") is not None
            for index in range(min(len(normalized), len(detail_rows)))
        ) and len(normalized) == len(detail_rows),
        "full_history_confirmed": bool(
            stats.get("is_full_history") or stats.get("full_history")
        ),
        "history_has_no_missing_rounds": int(
            stats.get("missing_rounds_count", 0) or 0
        )
        == 0,
    }
    scope = {
        "round_range": stats.get("analysis_round_range")
        or [1, stats.get("latest_round", 0)],
        "draw_count": int(stats.get("draw_count", 0) or 0),
        "latest_round": int(stats.get("latest_round", 0) or 0),
        "missing_rounds_count": int(stats.get("missing_rounds_count", 0) or 0),
        "candidate_count": int(stats.get("candidate_count", 0) or 0),
        "attempts": int(stats.get("attempts", 0) or 0),
    }
    reproducible_payload = {
        "proof_version": VERIFICATION_VERSION,
        "engine_version": stats.get("engine_version")
        or engine.get("engine_version")
        or engine.get("version"),
        "analysis_engine_version": engine.get("analysis_engine_version"),
        "ai_lab_stable_version_id": engine.get("ai_lab_stable_version_id", 0),
        "ai_lab_backtest_run_id": engine.get("ai_lab_backtest_run_id", 0),
        "round_no": int(round_no),
        "mode": str(mode),
        "member_grade": str(member_grade),
        "fixed_numbers": sorted(fixed_set),
        "excluded_numbers": sorted(excluded_set),
        "data_scope": scope,
        "methodology": list(stats.get("methodology") or []),
        "ensemble_report": engine.get("ensemble_report") or {},
        "combo_proofs": combo_proofs,
        "validations": validations,
    }
    canonical = json.dumps(
        reproducible_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    verification_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        **reproducible_payload,
        "verification_id": verification_id,
        "short_id": verification_id[:12].upper(),
        "passed": all(validations.values()),
        "selected_count": len(normalized),
        "runtime_metrics": {"generation_ms": stats.get("generation_ms")},
        "validation_linkage": {
            "ai_lab_profile_applied": bool(engine.get("ai_lab_profile_applied")),
            "ai_lab_stable_version_id": int(
                engine.get("ai_lab_stable_version_id", 0) or 0
            ),
            "ai_lab_stable_version_name": str(
                engine.get("ai_lab_stable_version_name") or ""
            ),
            "ai_lab_backtest_run_id": int(
                engine.get("ai_lab_backtest_run_id", 0) or 0
            ),
            "method": "과거 당첨정보를 보지 않는 회차별 순차검증(walk-forward)",
        },
        "factor_groups": [
            "최근·누적 빈도",
            "미출현 간격·모멘텀",
            "동반출현·트리플",
            "홀짝·구간·합계·AC",
            "조합 중복·번호 반복 억제",
            "회원·AI LAB 가중치",
            "5모델 앙상블 합의·포트폴리오 재선별",
        ],
    }
