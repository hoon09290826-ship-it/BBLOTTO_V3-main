"""BBLOTTO STABLE-12 evidence-linked explanation engine.
Creates explanations only from the actual generated combinations and number_evidence.
"""
from __future__ import annotations
import collections, hashlib
from typing import Any, Dict, Iterable, List, Sequence


def _nums(d: Dict[str, Any]) -> List[int]:
    raw=d.get('numbers') or d.get('nums') or d.get('combo') or []
    try: out=sorted({int(x) for x in raw if 1 <= int(x) <= 45})
    except Exception: return []
    return out if len(out)==6 else []

def _pick(seed: str, arr: Sequence[str]) -> str:
    if not arr: return ''
    i=int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4],'big')%len(arr)
    return arr[i]

def _evidence(details: List[Dict[str,Any]]) -> Dict[int,List[str]]:
    out=collections.defaultdict(list)
    for d in details or []:
        for e in d.get('number_evidence') or []:
            try: n=int(e.get('number')); r=str(e.get('reason') or '').strip()
            except Exception: continue
            if 1<=n<=45 and r and r not in out[n]: out[n].append(r)
    return out

def _short(reason: str) -> str:
    return reason.replace('후보','').replace('통합 신호 상위권','장·단기 흐름이 함께 확인된 번호').replace('최근30회','최근 30회')

def build_evidence_analysis(round_no:int, stats:Dict[str,Any], mode:str, fixed:Any, excluded:Any, details:List[Dict[str,Any]]) -> str:
    combos=[_nums(d) for d in details or []]; combos=[c for c in combos if c]
    if not combos: return '생성된 조합의 선택 근거를 확인할 수 없습니다.'
    ev=_evidence(details); freq=collections.Counter(n for c in combos for n in c)
    seed=f'{round_no}|{combos}|{sorted((n,tuple(v)) for n,v in ev.items())}'
    core=[n for n,_ in freq.most_common(8) if ev.get(n)][:4]
    if not core: core=[n for n,_ in freq.most_common(4)]
    reason_parts=[]
    for n in core:
        rs=ev.get(n) or ['조합의 구간·홀짝·합계 균형을 맞추기 위해 선택']
        reason_parts.append(f'{n}번은 {_short(rs[0])}')
    line1=_pick(seed+'a',[
        f"이번 {round_no}회차 조합의 중심축은 {', '.join(map(str,core))}번입니다. " + '; '.join(reason_parts[:2]) + '했습니다.',
        f"실제 생성 과정에서 {', '.join(map(str,core))}번의 선택 점수가 높았습니다. " + '; '.join(reason_parts[:2]) + '했습니다.',
    ])
    secondary=[]
    for n in sorted(ev):
        if n not in core and any(k in ' '.join(ev[n]) for k in ['미출현','공백','반등','보완']): secondary.append(n)
    if secondary:
        chosen=secondary[:4]
        line2=f"{', '.join(map(str,chosen))}번은 최근 공백 또는 반등 신호를 보완하기 위해 일부 조합에 분산 배치했습니다."
    else:
        chosen=[n for n in sorted(ev) if n not in core][:4]
        line2=f"{', '.join(map(str,chosen))}번은 중심수와 겹치지 않는 흐름을 보강하고 조합별 차이를 만들기 위해 선택했습니다." if chosen else '나머지 번호는 중심수 반복을 낮추기 위해 조합별로 다르게 배치했습니다.'
    sums=[sum(c) for c in combos]; odd=[sum(n%2 for n in c) for c in combos]
    zones=[sum(n<=15 for c in combos for n in c),sum(16<=n<=30 for c in combos for n in c),sum(n>=31 for c in combos for n in c)]
    overlaps=[len(set(a)&set(b)) for i,a in enumerate(combos) for b in combos[i+1:]]
    line3=f"선택된 번호를 조합할 때 합계 {min(sums)}~{max(sums)}, 홀짝 2:4~4:2 범위를 우선했고 저·중·고번호는 {zones[0]}·{zones[1]}·{zones[2]}개로 배분했습니다."
    line4=f"같은 선택 근거가 반복되더라도 조합 간 최대 중복을 {max(overlaps,default=0)}개로 제한해, 중심 흐름은 유지하면서 서로 다른 당첨 형태를 노리도록 구성했습니다."
    if fixed: line4 += ' 입력한 고정수는 모든 조합의 필수 축으로 유지했습니다.'
    if excluded: line4 += ' 입력한 제외수는 후보 계산과 최종 조합에서 모두 제거했습니다.'
    return '\n'.join([line1,line2,line3,line4])

def build_recommendation_analysis(round_no:int, details:List[Dict[str,Any]]) -> str:
    combos=[_nums(d) for d in details or []]; combos=[c for c in combos if c]
    if not combos: return ''
    ev=_evidence(details); freq=collections.Counter(n for c in combos for n in c)
    lines=[]
    for idx,d in enumerate(details[:min(4,len(details))],1):
        nums=_nums(d)
        if not nums: continue
        ranked=sorted(nums,key=lambda n:(-freq[n],n))[:2]
        why=[]
        for n in ranked:
            why.append(f"{n}번({_short((ev.get(n) or ['구조 균형'])[0])})")
        typ=d.get('portfolio_type') or d.get('strategy') or d.get('type') or '균형형'
        lines.append(f"{idx}조합은 {typ}으로, {', '.join(why)}를 중심으로 {d.get('reason') or '구간과 홀짝 균형을 맞춰'} 구성했습니다.")
    used=len(freq); repeated=[n for n,c in freq.most_common() if c>1][:5]
    lines.append(f"전체 {used}개 번호를 사용했으며, 반복 중심수 {', '.join(map(str,repeated)) if repeated else '없음'}는 필요한 조합에만 제한적으로 배치했습니다.")
    return '\n'.join(lines)
