from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Sequence, Tuple


ENSEMBLE_VERSION = "BBLOTTO_ENSEMBLE_SELECTOR_V1_20260724"
MODEL_WEIGHTS = {
    "engine": 0.25,
    "number_evidence": 0.25,
    "structure": 0.20,
    "cooccurrence": 0.15,
    "stability": 0.15,
}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize(values: Sequence[float]) -> List[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return [50.0 for _ in values]
    return [round((value - low) * 100.0 / (high - low), 4) for value in values]


def _raw_models(combo: Sequence[int], detail: Dict[str, Any]) -> Dict[str, float]:
    evidence = [
        item for item in (detail.get("number_evidence") or [])
        if isinstance(item, dict)
    ]
    selection_scores = [_float(item.get("selection_score")) for item in evidence]
    momentum = [_float(item.get("momentum")) for item in evidence]
    gaps = [_float(item.get("gap")) for item in evidence]
    hot_ranks = [
        _float(item.get("hot_rank"), 46.0)
        for item in evidence
        if item.get("hot_rank") is not None
    ]

    odd = int(detail.get("odd") or sum(int(number) % 2 for number in combo))
    zones = detail.get("zones") or [
        sum(1 <= int(number) <= 15 for number in combo),
        sum(16 <= int(number) <= 30 for number in combo),
        sum(31 <= int(number) <= 45 for number in combo),
    ]
    total = int(detail.get("sum") or sum(int(number) for number in combo))
    ac = _float(detail.get("ac"))
    max_recent_overlap = _float(detail.get("max_recent_overlap"))

    structure = (
        35.0 - abs(total - 140.0) * 0.22
        + 24.0 - abs(odd - 3) * 7.0
        + 24.0 - sum(abs(_float(zone) - 2.0) for zone in zones[:3]) * 4.0
        + min(17.0, ac * 2.0)
    )
    cooccurrence = (
        _float(detail.get("pair_strength")) * 8.0
        + _float(detail.get("triple_strength")) * 5.0
    )
    stability = (
        max(0.0, 24.0 - max_recent_overlap * 5.0)
        + max(0.0, 18.0 - (max(gaps, default=0.0) * 0.8))
        + max(0.0, 18.0 - abs(sum(momentum) * 10.0))
        + max(0.0, 20.0 - (sum(hot_ranks) / max(1, len(hot_ranks))) * 0.6)
    )
    return {
        "engine": _float(
            detail.get("raw_score")
            if detail.get("raw_score") is not None
            else detail.get("score")
        ),
        "number_evidence": sum(selection_scores) / max(1, len(selection_scores)),
        "structure": structure,
        "cooccurrence": cooccurrence,
        "stability": stability,
    }


def select_ensemble_portfolio(
    combos: Sequence[Sequence[int]],
    details: Sequence[Dict[str, Any]],
    target_count: int,
) -> Tuple[List[List[int]], List[Dict[str, Any]], Dict[str, Any]]:
    """Select the final portfolio from Stable-engine candidates.

    The Stable engine remains the candidate generator. This selector only
    compares its candidates through five independent views and records every
    component used for the final choice.
    """
    rows: List[Dict[str, Any]] = []
    for index, combo_value in enumerate(combos or []):
        combo = sorted({int(number) for number in combo_value})
        if len(combo) != 6 or not all(1 <= number <= 45 for number in combo):
            continue
        detail = (
            dict(details[index])
            if index < len(details) and isinstance(details[index], dict)
            else {}
        )
        rows.append({
            "source_index": index,
            "combo": combo,
            "detail": detail,
            "raw_models": _raw_models(combo, detail),
        })

    target = max(1, min(int(target_count or 1), len(rows)))
    if not rows:
        return [], [], {
            "version": ENSEMBLE_VERSION,
            "applied": False,
            "candidate_portfolio_count": 0,
            "selected_count": 0,
            "models": list(MODEL_WEIGHTS),
        }

    normalized_by_model: Dict[str, List[float]] = {}
    for model in MODEL_WEIGHTS:
        normalized_by_model[model] = _normalize(
            [row["raw_models"][model] for row in rows]
        )

    model_rankings: Dict[str, Dict[int, int]] = {}
    for model in MODEL_WEIGHTS:
        order = sorted(
            range(len(rows)),
            key=lambda idx: (
                -normalized_by_model[model][idx],
                rows[idx]["combo"],
            ),
        )
        model_rankings[model] = {
            row_index: rank + 1 for rank, row_index in enumerate(order)
        }

    for index, row in enumerate(rows):
        components = {
            model: normalized_by_model[model][index]
            for model in MODEL_WEIGHTS
        }
        consensus = sum(
            components[model] * MODEL_WEIGHTS[model]
            for model in MODEL_WEIGHTS
        )
        vote_cutoff = max(target, max(1, len(rows) // 2))
        votes = sum(
            model_rankings[model][index] <= vote_cutoff
            for model in MODEL_WEIGHTS
        )
        row["components"] = components
        row["consensus"] = round(consensus, 4)
        row["votes"] = votes
        row["model_ranks"] = {
            model: model_rankings[model][index] for model in MODEL_WEIGHTS
        }

    consensus_order = sorted(
        range(len(rows)),
        key=lambda idx: (
            -rows[idx]["consensus"],
            -rows[idx]["votes"],
            rows[idx]["combo"],
        ),
    )
    for rank, row_index in enumerate(consensus_order, 1):
        rows[row_index]["ensemble_candidate_rank"] = rank

    selected_indices: List[int] = []
    number_usage: Counter[int] = Counter()
    strategy_usage: Counter[str] = Counter()
    selection_log: List[Dict[str, Any]] = []
    while len(selected_indices) < target:
        best_index = None
        best_tuple = None
        best_adjustments: Dict[str, Any] = {}
        for index, row in enumerate(rows):
            if index in selected_indices:
                continue
            combo = row["combo"]
            overlaps = [
                len(set(combo) & set(rows[chosen]["combo"]))
                for chosen in selected_indices
            ]
            max_overlap = max(overlaps, default=0)
            repeat_penalty = sum(max(0, number_usage[number] - 1) for number in combo) * 2.1
            overlap_penalty = max(0, max_overlap - 2) * 7.5
            strategy = str(
                row["detail"].get("strategy")
                or row["detail"].get("type")
                or "균형형"
            )
            strategy_penalty = max(0, strategy_usage[strategy] - 1) * 1.8
            adjusted = (
                row["consensus"]
                + row["votes"] * 1.25
                - repeat_penalty
                - overlap_penalty
                - strategy_penalty
            )
            candidate = (
                round(adjusted, 6),
                row["votes"],
                row["consensus"],
                tuple(-number for number in combo),
            )
            if best_tuple is None or candidate > best_tuple:
                best_index = index
                best_tuple = candidate
                best_adjustments = {
                    "adjusted_score": round(adjusted, 4),
                    "repeat_penalty": round(repeat_penalty, 4),
                    "overlap_penalty": round(overlap_penalty, 4),
                    "strategy_penalty": round(strategy_penalty, 4),
                    "max_overlap": max_overlap,
                }
        if best_index is None:
            break
        selected_indices.append(best_index)
        selected_row = rows[best_index]
        number_usage.update(selected_row["combo"])
        strategy_usage.update([
            str(
                selected_row["detail"].get("strategy")
                or selected_row["detail"].get("type")
                or "균형형"
            )
        ])
        selection_log.append({
            "selection_rank": len(selected_indices),
            "numbers": selected_row["combo"],
            "ensemble_candidate_rank": selected_row["ensemble_candidate_rank"],
            "consensus_score": selected_row["consensus"],
            "votes": selected_row["votes"],
            **best_adjustments,
        })

    selected_combos: List[List[int]] = []
    selected_details: List[Dict[str, Any]] = []
    for selection_rank, row_index in enumerate(selected_indices, 1):
        row = rows[row_index]
        detail = dict(row["detail"])
        trace = dict(detail.get("selection_trace") or {})
        trace.update({
            "ensemble_version": ENSEMBLE_VERSION,
            "ensemble_candidate_rank": row["ensemble_candidate_rank"],
            "ensemble_selection_rank": selection_rank,
            "ensemble_consensus_score": round(row["consensus"], 2),
            "ensemble_votes": row["votes"],
            "ensemble_components": row["components"],
            "ensemble_model_ranks": row["model_ranks"],
        })
        reasons = list(detail.get("reasons") or [])
        reasons.append(
            f"앙상블 5개 관점 중 {row['votes']}개 우선권 · "
            f"후보 {row['ensemble_candidate_rank']}위"
        )
        detail.update({
            "numbers": list(row["combo"]),
            "selection_rank": selection_rank,
            "ensemble_version": ENSEMBLE_VERSION,
            "ensemble_score": round(row["consensus"], 2),
            "ensemble_votes": row["votes"],
            "ensemble_candidate_rank": row["ensemble_candidate_rank"],
            "ensemble_components": row["components"],
            "ensemble_model_ranks": row["model_ranks"],
            "selection_trace": trace,
            "reasons": reasons,
            "reason": " / ".join(str(reason) for reason in reasons if reason),
        })
        selected_combos.append(list(row["combo"]))
        selected_details.append(detail)

    max_overlap = 0
    for i, combo in enumerate(selected_combos):
        for other in selected_combos[i + 1:]:
            max_overlap = max(max_overlap, len(set(combo) & set(other)))
    report = {
        "version": ENSEMBLE_VERSION,
        "applied": len(rows) > target,
        "candidate_portfolio_count": len(rows),
        "selected_count": len(selected_combos),
        "models": list(MODEL_WEIGHTS),
        "model_weights": dict(MODEL_WEIGHTS),
        "max_final_overlap": max_overlap,
        "unique_final_numbers": len(number_usage),
        "selection_log": selection_log,
    }
    return selected_combos, selected_details, report
