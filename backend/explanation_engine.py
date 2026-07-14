"""BBLOTTO STABLE-13 factual, evidence-linked explanation engine."""
from __future__ import annotations
import collections, hashlib
from typing import Any, Dict, List, Sequence


def _nums(d: Dict[str, Any]) -> List[int]:
    try:
        out=sorted({int(x) for x in (d.get('numbers') or d.get('nums') or d.get('combo') or []) if 1<=int(x)<=45})
    except Exception:
        return []
    return out if len(out)==6 else []


def _pick(seed:str, arr:Sequence[str])->str:
    return arr[int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4],'big')%len(arr)] if arr else ''


def _ev(details:List[Dict[str,Any]])->Dict[int,Dict[str,Any]]:
    best={}
    for d in details or []:
        for e in d.get('number_evidence') or []:
            try: n=int(e.get('number'))
            except Exception: continue
            if 1<=n<=45:
                cur=best.setdefault(n,dict(e))
                for k,v in e.items():
                    if cur.get(k) in (None,'',[],0) and v not in (None,'',[]): cur[k]=v
    return best


def _why(n:int,e:Dict[str,Any])->str:
    f10=int(e.get('freq10') or 0); f30=int(e.get('freq30') or 0); f100=int(e.get('freq100') or 0); gap=int(e.get('gap') or 0)
    role=e.get('role') or '균형수'
    if role=='강세수': return f"최근 10회 {f10}회·30회 {f30}회 출현한 강세 흐름"
    if role=='반등수': return f"최근 {gap}회 공백을 반영한 반등 신호"
    if f100: return f"최근 100회 {f100}회 출현과 구간 균형을 함께 반영"
    return str(e.get('reason') or '조합 구조 균형을 위해 선택')


def build_evidence_analysis(round_no:int, stats:Dict[str,Any], mode:str, fixed:Any, excluded:Any, details:List[Dict[str,Any]])->str:
    combos=[_nums(d) for d in details or []]; combos=[c for c in combos if c]
    if not combos: return '생성된 조합의 선택 근거를 확인할 수 없습니다.'
    ev=_ev(details); freq=collections.Counter(n for c in combos for n in c)
    seed=f'{round_no}|{combos}|{[(n,ev.get(n,{})) for n in sorted(ev)]}'
    ranked=sorted(freq, key=lambda n:(-(freq[n]*10 + (50-(ev.get(n,{}).get('hot_rank') or 50))), n))
    core=ranked[:3]
    core_text='; '.join(f"{n}번은 {_why(n,ev.get(n,{}))}" for n in core)
    line1=_pick(seed+'1',[
        f"이번 {round_no}회차 생성에서 중심축은 {', '.join(map(str,core))}번입니다. {core_text}. 이 근거를 바탕으로 반복 배치했습니다.",
        f"실제 생성 점수와 사용 빈도를 함께 비교한 결과 {', '.join(map(str,core))}번이 핵심수로 선정됐습니다. {core_text}. 해당 근거를 반영했습니다.",
        f"이번 번호의 핵심은 {', '.join(map(str,core))}번입니다. {core_text}. 그래서 조합의 중심 역할을 맡겼습니다.",
    ])
    roles=collections.defaultdict(list)
    for n,e in ev.items(): roles[e.get('role') or '균형수'].append(n)
    line2=f"구성은 강세수 {len(roles['강세수'])}개, 반등수 {len(roles['반등수'])}개, 균형수 {len(roles['균형수'])}개를 사용해 한 흐름에만 치우치지 않도록 했습니다."
    sums=[sum(c) for c in combos]; odds=[sum(n%2 for n in c) for c in combos]
    zone_tot=[sum(n<=15 for c in combos for n in c),sum(16<=n<=30 for c in combos for n in c),sum(n>=31 for c in combos for n in c)]
    line3=f"실제 조합 합계는 {min(sums)}~{max(sums)}, 홀수는 조합당 {min(odds)}~{max(odds)}개이며, 저·중·고번호 사용량은 {zone_tot[0]}·{zone_tot[1]}·{zone_tot[2]}개입니다."
    pairs=[]
    for n,e in ev.items():
        for p in e.get('partners') or []:
            try:
                m=int(p.get('number')); cnt=int(p.get('count') or 0)
                if n<m and cnt>0: pairs.append((cnt,n,m))
            except Exception: pass
    pairs=sorted(set(pairs), reverse=True)[:3]
    if pairs:
        line4="동반출현 근거는 " + ', '.join(f"{a}-{b}번({cnt}회)" for cnt,a,b in pairs) + "을 우선 참고했지만, 모든 조합에 반복하지 않고 분산했습니다."
    else:
        overlaps=[len(set(a)&set(b)) for i,a in enumerate(combos) for b in combos[i+1:]]
        line4=f"특정 번호쌍의 과도한 반복을 피하고 조합 간 최대 중복을 {max(overlaps,default=0)}개로 제한해 서로 다른 구조를 확보했습니다."
    if fixed: line4 += ' 입력한 고정수는 모든 조합의 공통 축으로 유지했습니다.'
    if excluded: line4 += ' 입력한 제외수는 후보와 최종 결과에서 모두 제거했습니다.'
    return '\n'.join((line1,line2,line3,line4))


def build_recommendation_analysis(round_no:int, details:List[Dict[str,Any]])->str:
    ev=_ev(details); lines=[]
    valid=[d for d in details or [] if _nums(d)]
    for idx,d in enumerate(valid,1):
        nums=_nums(d); typ=d.get('portfolio_type') or d.get('strategy') or d.get('type') or '균형형'
        scored=sorted(nums,key=lambda n:((ev.get(n,{}).get('hot_rank') or 99),-(ev.get(n,{}).get('freq30') or 0),n))
        focus=scored[:2]
        reasons=' / '.join(f"{n}번: {_why(n,ev.get(n,{}))}" for n in focus)
        zones=d.get('zones') or [sum(n<=15 for n in nums),sum(16<=n<=30 for n in nums),sum(n>=31 for n in nums)]
        odd=int(d.get('odd') if d.get('odd') is not None else sum(n%2 for n in nums))
        ac=d.get('ac','-')
        lines.append(f"{idx}조합 [{typ}] {reasons}. 합계 {sum(nums)}, 홀짝 {odd}:{6-odd}, 구간 {zones[0]}-{zones[1]}-{zones[2]}, AC {ac}로 마무리했습니다.")
    used=collections.Counter(n for d in valid for n in _nums(d))
    repeated=[f"{n}번 {c}회" for n,c in used.most_common(5) if c>1]
    lines.append(f"전체 요약: {len(used)}개 번호를 활용했고, 주요 반복수는 {', '.join(repeated) if repeated else '없습니다'}. 각 조합은 실제 번호별 근거와 구조 수치를 기준으로 따로 설계했습니다.")
    return '\n'.join(lines)
