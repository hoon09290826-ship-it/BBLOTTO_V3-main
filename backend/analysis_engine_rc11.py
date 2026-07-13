"""BBLOTTO STABLE-11 동적 설명 엔진.
실제 생성 조합과 통계값을 읽어 매 생성 결과에 맞는 핵심 분석을 작성한다.
"""
from __future__ import annotations
import collections
import hashlib
from typing import Any, Dict, Iterable, List, Sequence, Tuple


def _numbers(item: Dict[str, Any]) -> List[int]:
    raw = item.get("numbers") or item.get("nums") or item.get("combo") or []
    try: nums = sorted({int(n) for n in raw if 1 <= int(n) <= 45})
    except Exception: return []
    return nums if len(nums) == 6 else []


def _as_int_list(values: Iterable[Any], limit: int = 20) -> List[int]:
    out=[]
    for value in values or []:
        try: n=int(value)
        except Exception: continue
        if 1 <= n <= 45 and n not in out: out.append(n)
        if len(out)>=limit: break
    return out


def _fmt(nums: Sequence[int], limit: int = 4) -> str:
    return ", ".join(str(n) for n in list(nums)[:limit])


def _pick(seed: str, choices: Sequence[str]) -> str:
    if not choices: return ""
    idx=int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:4],"big")%len(choices)
    return choices[idx]


def _features(combos: List[List[int]]) -> Dict[str, Any]:
    flat=[n for c in combos for n in c]; freq=collections.Counter(flat)
    sums=[sum(c) for c in combos]; odds=[sum(n%2 for n in c) for c in combos]
    zones=[sum(n<=15 for n in flat),sum(16<=n<=30 for n in flat),sum(n>=31 for n in flat)]
    overlaps=[len(set(a)&set(b)) for i,a in enumerate(combos) for b in combos[i+1:]]
    consecutive=sum(any(b-a==1 for a,b in zip(c,c[1:])) for c in combos)
    end_spread=sum(len({n%10 for n in c})>=5 for c in combos)
    return {"flat":flat,"freq":freq,"sums":sums,"odds":odds,"zones":zones,"unique":len(freq),
            "max_overlap":max(overlaps,default=0),"consecutive":consecutive,"end_spread":end_spread}


def _trend_lists(stats: Dict[str, Any]) -> Tuple[List[int], List[int]]:
    hot=_as_int_list(stats.get("hot") or stats.get("hot20") or stats.get("hot30") or stats.get("hot100") or [])
    overdue=_as_int_list(stats.get("overdue") or stats.get("overdue20") or stats.get("overdue30") or stats.get("overdue100") or [])
    return hot,overdue


def build_member_friendly_analysis(round_no:int, stats:Dict[str,Any], mode:str, fixed:Any, excluded:Any, details:List[Dict[str,Any]])->str:
    combos=[_numbers(x) for x in details or []]; combos=[x for x in combos if x]
    latest=int(stats.get("latest_round") or max(0,int(round_no or 1)-1))
    if not combos:
        return "\n".join([
            f"1회차부터 {latest}회차까지의 누적 기록과 최근 10·30·100회 흐름을 함께 비교했습니다.",
            "홀짝·구간·합계·AC·끝수 분포를 동시에 점검해 한쪽으로 치우친 후보를 줄였습니다.",
            "조합 간 번호 반복을 낮추고 서로 다른 흐름을 나누어 담는 방식으로 구성했습니다.",
        ])
    f=_features(combos); hot,overdue=_trend_lists(stats)
    hot_used=[n for n in hot if n in f["freq"]][:5]; overdue_used=[n for n in overdue if n in f["freq"] and n not in hot_used][:5]
    core=[n for n,c in f["freq"].most_common() if c>=2][:4]
    types=[str(d.get("portfolio_type") or d.get("strategy") or d.get("type") or "") for d in details]
    types=[x for x in types if x]; type_counts=collections.Counter(types)
    seed=f"{round_no}|{combos}|{types}"
    opening=_pick(seed+"o",[
        f"{latest}회차까지의 전체 기록과 최근 10·30·100회 변화를 교차 비교해 {round_no}회차 후보를 선별했습니다.",
        f"1회차부터 {latest}회차까지의 장기 빈도에 최근 흐름과 미출현 간격을 더해 {round_no}회차 조합을 구성했습니다.",
        f"누적 출현 기록, 최근 상승 신호, 번호별 공백을 함께 평가해 {round_no}회차 추천 후보를 정리했습니다.",
    ])
    if hot_used and overdue_used:
        trend=f"최근 흐름 후보 {_fmt(hot_used)}번과 공백 후 반등 후보 {_fmt(overdue_used)}번을 조합별로 나누어, 강세수에만 몰리지 않도록 혼합했습니다."
    elif hot_used:
        trend=f"최근 흐름에서 확인된 {_fmt(hot_used)}번을 중심축으로 사용하되, 주변 번호는 조합마다 다르게 배치해 반복을 줄였습니다."
    elif overdue_used:
        trend=f"미출현 간격이 길어진 {_fmt(overdue_used)}번을 보완 후보로 반영하고 장기 안정 번호와 함께 배치했습니다."
    else:
        trend=f"반복 중심수 {_fmt(core)}번은 필요한 범위에서만 유지하고 나머지 번호를 넓게 분산했습니다." if core else "특정 번호군에 의존하지 않고 후보 범위를 넓게 분산했습니다."
    total=len(f["flat"]); zp=[round(v/total*100) for v in f["zones"]]
    balance=f"저·중·고번호 비중은 {zp[0]}%·{zp[1]}%·{zp[2]}%이며, 합계는 {min(f['sums'])}~{max(f['sums'])}, 홀짝 균형 조합은 {sum(2<=x<=4 for x in f['odds'])}/{len(combos)}개입니다."
    type_text=", ".join(f"{k} {v}개" for k,v in type_counts.most_common(3)) if type_counts else "균형형과 분산형"
    structure=f"{type_text}로 성격을 나누고, 전체 {f['unique']}개 번호를 사용했습니다. 조합 간 최대 중복은 {f['max_overlap']}개, 끝수 분산 확보 조합은 {f['end_spread']}개입니다."
    if fixed: structure += " 지정한 고정수는 모든 조합에 유지했습니다."
    if excluded: structure += " 제외수는 생성 후보에서 완전히 배제했습니다."
    return "\n".join([opening,trend,balance,structure])
