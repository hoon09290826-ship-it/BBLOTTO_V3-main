from __future__ import annotations

import hashlib
import statistics
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Sequence

EXPLANATION_ENGINE_VERSION = "BBLOTTO_AI_EXPLANATION_V15_TRACEABLE"


def _i(v: Any, d: int = 0) -> int:
    try: return int(v)
    except (TypeError, ValueError): return d


def _f(v: Any, d: float = 0.0) -> float:
    try: return float(v)
    except (TypeError, ValueError): return d


def _nums(d: Mapping[str, Any]) -> List[int]:
    raw=d.get("numbers") or d.get("nums") or d.get("combo") or []
    out=[]
    for v in raw if isinstance(raw,(list,tuple,set)) else []:
        n=_i(v,-1)
        if 1<=n<=45 and n not in out: out.append(n)
    return sorted(out) if len(out)==6 else []


def _valid(details: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out=[]
    for src in details or []:
        if not isinstance(src,Mapping): continue
        nums=_nums(src)
        if nums:
            d=dict(src); d["numbers"]=nums; out.append(d)
    return out


def _variant(seed: str, options: Sequence[str]) -> str:
    if not options: return ""
    idx=int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8],16)%len(options)
    return options[idx]


def _ev_map(details: Sequence[Mapping[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out={}
    for d in details:
        for ev in d.get("number_evidence") or []:
            if isinstance(ev,Mapping) and 1<=_i(ev.get("number"),-1)<=45:
                out[_i(ev.get("number"))]=dict(ev)
    return out


def _fact(n:int, ev:Mapping[str,Any]) -> str:
    factors=ev.get("factors") or []
    texts=[str(x.get("text")) for x in factors if isinstance(x,Mapping) and x.get("text")]
    if texts: return f"{n}번은 " + "·".join(texts[:2])
    return f"{n}번은 최근 10회 {_i(ev.get('freq10'))}회, 30회 {_i(ev.get('freq30'))}회, 미출현 {_i(ev.get('gap'))}회"


def _metric(d:Mapping[str,Any]) -> Dict[str,Any]:
    nums=d["numbers"]
    odd=_i(d.get("odd"),sum(n%2 for n in nums)); zones=d.get("zones")
    if not isinstance(zones,(list,tuple)) or len(zones)!=3:
        zones=[sum(n<=15 for n in nums),sum(16<=n<=30 for n in nums),sum(n>=31 for n in nums)]
    return {"sum":_i(d.get("sum"),sum(nums)),"odd":odd,"even":_i(d.get("even"),6-odd),"zones":[_i(x) for x in zones],"ac":_i(d.get("ac")),"pair":_f(d.get("pair_strength")),"score":_f(d.get("score")),"base":_f(d.get("base_score",d.get("score"))),"div":_f(d.get("diversity_penalty")),"ov":_f(d.get("overlap_penalty")),"type":str(d.get("type") or "균형형")}


def build_round_analysis(round_no:int, stats:Mapping[str,Any]|None, mode:str, fixed:Any, excluded:Any, details:Sequence[Mapping[str,Any]]) -> str:
    ds=_valid(details)
    if not ds: return "추천 조합의 실제 근거 데이터가 없어 설명을 생성하지 못했습니다."
    evs=_ev_map(ds); usage=Counter(n for d in ds for n in d["numbers"])
    seed=f"{round_no}|"+"|".join("-".join(map(str,d["numbers"])) for d in ds)

    # 핵심수는 단순 반복 횟수가 아니라 실제 최종 가중치와 사용 횟수를 함께 반영
    core=sorted(usage,key=lambda n:(-(usage[n]*10+_f(evs.get(n,{}).get('selection_score'))),n))[:4]
    core_facts=[f"{_fact(n,evs.get(n,{}))} 근거로 {usage[n]}개 조합에 반영" for n in core]
    line1=_variant(seed+"a",[
        f"{round_no}회차 핵심수는 " + ", ".join(core_facts) + "했습니다.",
        "실제 생성 결과에서 " + ", ".join(core_facts) + "했고, 이 번호들이 조합의 중심축이 됐습니다.",
        "번호별 최종 가중치와 채택 횟수를 대조한 결과 " + ", ".join(core_facts) + "했습니다.",
    ])

    best=max(ds,key=lambda d:_f(d.get("score"))); m=_metric(best); combo="-".join(map(str,best["numbers"]))
    topnums=sorted(best["numbers"],key=lambda n:-_f(evs.get(n,{}).get("selection_score")))[:3]
    why="; ".join(_fact(n,evs.get(n,{})) for n in topnums)
    penalties=[]
    if m["div"]>0: penalties.append(f"번호 반복 감점 {m['div']:.1f}")
    if m["ov"]>0: penalties.append(f"조합 중복 감점 {m['ov']:.1f}")
    penalty_text=(", "+"·".join(penalties)+"을 반영한 뒤") if penalties else ""
    line2=_variant(seed+"b",[
        f"대표 조합 [{combo}]은 {why}를 결합했고{penalty_text} 최종 {m['score']:.1f}점으로 선택됐습니다.",
        f"[{combo}]은 {why} 때문에 후보군에서 앞섰으며{penalty_text} 포트폴리오 최종점수 {m['score']:.1f}점을 받았습니다.",
        f"최고점 조합 [{combo}]의 직접 선택 근거는 {why}이며{penalty_text} 최종 선별됐습니다.",
    ])
    line3=_variant(seed+"c",[
        f"이 조합은 홀짝 {m['odd']}:{m['even']}, 구간 {m['zones'][0]}-{m['zones'][1]}-{m['zones'][2]}, 합계 {m['sum']}, AC {m['ac']}, 동반출현 {m['pair']:.1f} 조건을 충족했습니다.",
        f"패턴 검증 결과 합계 {m['sum']}·AC {m['ac']}·홀짝 {m['odd']}:{m['even']}·구간 {m['zones'][0]}-{m['zones'][1]}-{m['zones'][2]}였고 동반출현 점수는 {m['pair']:.1f}였습니다.",
    ])

    combos=[d["numbers"] for d in ds]; sums=[sum(c) for c in combos]; unique=len(usage); maxuse=max(usage.values())
    overlaps=[len(set(a)&set(b)) for i,a in enumerate(combos) for b in combos[i+1:]]
    line4=_variant(seed+"d",[
        f"전체 {len(combos)}개 조합은 {unique}개 번호를 사용했고, 한 번호는 최대 {maxuse}회, 조합 간 중복은 최대 {max(overlaps,default=0)}개로 제한했으며 합계는 {min(sums)}~{max(sums)}에 분산했습니다.",
        f"포트폴리오에서는 {unique}개 번호로 분산하고 최대 반복 {maxuse}회·최대 겹침 {max(overlaps,default=0)}개를 유지해 특정 번호와 패턴의 편중을 줄였습니다.",
    ])
    if str(fixed or '').strip() or str(excluded or '').strip():
        line4 += " 입력한 고정수와 제외수 조건도 최종 조합에 그대로 적용했습니다."
    return "\n".join([line1,line2,line3,line4])
