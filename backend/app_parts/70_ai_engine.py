# Extracted from legacy backend/app.py lines 3922-4849.
@app.get('/api/ai-engine/summary')
def ai_engine_summary(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    st=latest_stats(120)
    return {
        'latest_round':st.get('latest_round'),
        'hot':st['hot'][:12],
        'cold':st['cold'][:12],
        'overdue':st['overdue'][:12],
        'avg_sum30':st.get('avg_sum30'),
        'avg_ac30':st.get('avg_ac30'),
        'pair_top':st.get('pair_top',[])[:10],
        'end_counts':st.get('end_counts'),
        'zone_counts':st.get('zone_counts'),
    }

# =========================================================
# BBLOTTO PRO V34 - PRIORITY 1 VIP AI ENGINE FINAL PATCH
# 기존 API/프론트 호출명은 그대로 유지하고, 엔진 로직만 최종 우선 적용합니다.
# =========================================================

V34_AI_ENGINE_VERSION = 'V34_PRIORITY1_VIP_AI_FINAL'

def _v34_draws(limit=200):
    """draws 테이블 구조(numbers JSON)을 기준으로 최근 회차를 안전하게 읽습니다."""
    with con() as c:
        rows = c.execute('SELECT * FROM draws ORDER BY round_no DESC LIMIT ?', (int(limit),)).fetchall()
    draws=[]
    for r in rows:
        nums=parse_nums(r['numbers'] if 'numbers' in r.keys() else '')
        if len(nums)==6:
            draws.append({'round_no':r['round_no'], 'draw_date':r['draw_date'], 'numbers':nums, 'bonus':r['bonus']})
    return draws

def _v34_ac(nums):
    nums=sorted(parse_nums(nums)); diffs=set()
    for i,a in enumerate(nums):
        for b in nums[i+1:]: diffs.add(abs(b-a))
    return max(0, len(diffs)-5)

def _v34_cons(nums):
    nums=sorted(parse_nums(nums)); return sum(1 for a,b in zip(nums,nums[1:]) if b-a==1)

def _v34_zones(nums):
    nums=parse_nums(nums); return [sum(1<=n<=15 for n in nums), sum(16<=n<=30 for n in nums), sum(31<=n<=45 for n in nums)]

def _v34_similarity(a,b):
    return len(set(a)&set(b))

def _v34_latest_stats(limit=200):
    draws=_v34_draws(limit)
    windows=[10,30,50,100,200]
    freq={w:{n:0 for n in range(1,46)} for w in windows}
    last_seen={n:999 for n in range(1,46)}
    pair_counter=collections.Counter(); triple_counter=collections.Counter()
    end_counts={i:0 for i in range(10)}; zone_counts={'1~15':0,'16~30':0,'31~45':0}
    sums=[]; acs=[]; odd_total=0
    latest_nums=set(draws[0]['numbers']) if draws else set()
    for idx,d in enumerate(draws):
        nums=d['numbers']
        for w in windows:
            if idx<w:
                for n in nums: freq[w][n]+=1
        for n in nums:
            if last_seen[n]==999: last_seen[n]=idx
        if idx<50:
            for a,b in itertools.combinations(nums,2): pair_counter[tuple(sorted((a,b)))] += 1
            for t in itertools.combinations(nums,3): triple_counter[tuple(sorted(t))] += 1
        if idx<30:
            sums.append(sum(nums)); acs.append(_v34_ac(nums)); odd_total += sum(n%2 for n in nums)
            for n in nums:
                end_counts[n%10]+=1
                if n<=15: zone_counts['1~15']+=1
                elif n<=30: zone_counts['16~30']+=1
                else: zone_counts['31~45']+=1
    weighted={}
    for n in range(1,46):
        score=freq[10][n]*2.80 + freq[30][n]*1.55 + freq[50][n]*1.10 + freq[100][n]*0.75 + freq[200][n]*0.35
        # 직전 회차 번호는 완전 제외하지 않고 과반영만 방지
        if n in latest_nums: score -= 1.75
        # 미출현/저출현 반등 후보 보정
        if last_seen[n] >= 10: score += 0.75
        if last_seen[n] >= 18: score += 1.15
        if last_seen[n] >= 25: score += 1.30
        weighted[n]=round(score,4)
    avg=sum(weighted.values())/45 if weighted else 1
    hot=sorted(range(1,46), key=lambda n:(-weighted[n], last_seen[n], n))[:18]
    cold=sorted(range(1,46), key=lambda n:(freq[30][n], -last_seen[n], n))[:18]
    overdue=sorted(range(1,46), key=lambda n:(-last_seen[n], freq[100][n], n))[:18]
    mid=sorted(range(1,46), key=lambda n:(abs(weighted[n]-avg), n))[:18]
    return {
        'engine_version':V34_AI_ENGINE_VERSION, 'draws':draws, 'latest_round':draws[0]['round_no'] if draws else 0,
        'freq':freq[100], 'freq10':freq[10], 'freq30':freq[30], 'freq50':freq[50], 'freq100':freq[100], 'freq200':freq[200],
        'weighted_score':weighted, 'last_seen':last_seen, 'hot':hot, 'cold':cold, 'mid':mid, 'overdue':overdue,
        'pair_counter':pair_counter, 'triple_counter':triple_counter,
        'pair_top':[{'pair':list(k),'count':v} for k,v in pair_counter.most_common(20)],
        'end_counts':end_counts, 'zone_counts':zone_counts,
        'odd_ratio':round(odd_total/max(1,len(draws[:30])*6),3),
        'avg_sum30':round(sum(sums)/len(sums),1) if sums else 0,
        'avg_ac30':round(sum(acs)/len(acs),1) if acs else 0,
    }

def latest_stats(limit=200):
    return _v34_latest_stats(limit)

def _v34_weights(st, mode='balanced'):
    avg=sum(st['weighted_score'].values())/45 if st.get('weighted_score') else 1
    hot=set(st['hot'][:12]); cold=set(st['cold'][:12]); overdue=set(st['overdue'][:12]); mid=set(st['mid'][:12])
    weights={}
    for n in range(1,46):
        w=1.0 + max(0, st['weighted_score'].get(n,0))/max(1,avg)*0.70
        if n in hot: w += 1.65
        if n in overdue: w += 1.25
        if n in cold: w += 0.70
        if n in mid: w += 0.35
        if mode=='conservative':
            if 11<=n<=35: w += 0.75
            if n in hot or n in mid: w += 0.35
        elif mode=='aggressive':
            if n in overdue or n in cold: w += 0.85
            if n<=10 or n>=36: w += 0.35
        else:
            if 8<=n<=40: w += 0.30
        weights[n]=max(0.1, round(w,4))
    return weights

def _v34_choice(pool, weights):
    pool=[n for n in pool if n in weights]
    if not pool: return None
    total=sum(weights[n] for n in pool); r=random.random()*total
    for n in pool:
        r-=weights[n]
        if r<=0: return n
    return pool[-1]

def _v34_pair_score(combo, st):
    pc=st.get('pair_counter') or collections.Counter()
    return sum(pc.get(tuple(sorted((a,b))),0) for a,b in itertools.combinations(combo,2))

def _v34_triple_penalty(combo, st):
    tc=st.get('triple_counter') or collections.Counter()
    # 최근 50회에서 동일 3수 묶음이 너무 강하면 과적합 방지로 감점
    return sum(1 for t in itertools.combinations(combo,3) if tc.get(tuple(sorted(t)),0) >= 2)

def combo_score(combo, st):
    c=sorted(parse_nums(combo))
    if len(c)!=6: return 0
    odd=sum(n%2 for n in c); total=sum(c); zones=_v34_zones(c); ac=_v34_ac(c); cons=_v34_cons(c); ends=len(set(n%10 for n in c))
    hot_hit=len(set(c)&set(st['hot'][:10])); cold_hit=len(set(c)&set(st['cold'][:10])); overdue_hit=len(set(c)&set(st['overdue'][:10]))
    pair_score=_v34_pair_score(c,st); triple_penalty=_v34_triple_penalty(c,st)
    score=60
    score += 12 if odd in (2,3,4) else -14
    if max(zones)<=3 and min(zones)>=1: score+=12
    elif max(zones)==4 and min(zones)>=1: score+=4
    else: score-=13
    if 95<=total<=180: score+=10
    elif 85<=total<=195: score+=4
    else: score-=14
    if 6<=ac<=10: score+=10
    elif 5<=ac<=12: score+=4
    else: score-=9
    if cons<=1: score+=7
    elif cons==2: score+=1
    else: score-=10
    score += 5 if ends>=5 else (2 if ends==4 else -7)
    if 1<=hot_hit<=3: score+=6
    elif hot_hit>=4: score-=3
    if 1<=cold_hit<=3: score+=4
    if 1<=overdue_hit<=3: score+=5
    if 3<=pair_score<=14: score+=5
    elif pair_score>18: score-=4
    score -= triple_penalty*3
    score += min(5, sum((st.get('freq100') or st.get('freq')).get(n,0) for n in c)//8)
    return max(0, min(99, int(round(score))))

def tags_for_combo(combo, st):
    c=sorted(parse_nums(combo)); tags=[]
    if len(set(c)&set(st['hot'][:10]))>=2: tags.append('핵심수 반영')
    if len(set(c)&set(st['overdue'][:10]))>=1: tags.append('미출현 보강')
    if len(set(c)&set(st['cold'][:10]))>=1: tags.append('저출현 후보')
    if sum(n%2 for n in c) in (2,3,4): tags.append('홀짝 균형')
    if max(_v34_zones(c))<=3 and min(_v34_zones(c))>=1: tags.append('구간 분산')
    if 6<=_v34_ac(c)<=10: tags.append('AC 적정')
    if len(set(n%10 for n in c))>=5: tags.append('끝수 분산')
    if 3<=_v34_pair_score(c,st)<=14: tags.append('동반출현 반영')
    return tags[:5] or ['VIP 균형 조합']

def _combo_detail(combo, st):
    c=sorted(parse_nums(combo))
    return {'numbers':c,'score':combo_score(c,st),'tags':tags_for_combo(c,st),'sum':sum(c),'odd':sum(n%2 for n in c),'even':6-sum(n%2 for n in c),'zones':_v34_zones(c),'ac':_v34_ac(c),'consecutive':_v34_cons(c),'end_unique':len(set(n%10 for n in c)),'hot_hit':len(set(c)&set(st['hot'][:10])),'cold_hit':len(set(c)&set(st['cold'][:10])),'overdue_hit':len(set(c)&set(st['overdue'][:10])),'pair_score':_v34_pair_score(c,st)}

def _engine_summary(details, st):
    if not details:
        return {'engine_version':V34_AI_ENGINE_VERSION,'avg_score':0,'filters':['생성 데이터 없음']}
    return {
        'engine_version':V34_AI_ENGINE_VERSION,
        'avg_score':round(sum(d['score'] for d in details)/len(details),1),
        'max_score':max(d['score'] for d in details), 'min_score':min(d['score'] for d in details),
        'avg_sum':round(sum(d['sum'] for d in details)/len(details),1),
        'avg_ac':round(sum(d['ac'] for d in details)/len(details),1),
        'pair_avg':round(sum(d['pair_score'] for d in details)/len(details),1),
        'odd_even':{'odd':sum(d['odd'] for d in details),'even':sum(d['even'] for d in details)},
        'sections':[sum(d['zones'][i] for d in details) for i in range(3)],
        'hot':st['hot'][:8], 'cold':st['cold'][:8], 'overdue':st['overdue'][:8], 'pair_top':st.get('pair_top',[])[:5],
        'filters':['최근 10/30/50/100/200회 가중치','동반출현 보정','과거 3수 과적합 감점','홀짝 2:4~4:2','구간 몰림 제한','합계 85~195','AC 4~12','연속수 2쌍 이하','끝수 4개 이상','조합간 유사도 제한'],
    }

def make_premium_combos(count=10, fixed='', excluded='', mode='balanced'):
    st=latest_stats(200); target=max(1,min(50,int(count or 10)))
    fixed_set=set(parse_nums(fixed)); excluded_set=set(parse_nums(excluded))-fixed_set
    if len(fixed_set)>6: fixed_set=set(sorted(fixed_set)[:6])
    pool=[n for n in range(1,46) if n not in excluded_set and n not in fixed_set]
    if len(pool)+len(fixed_set)<6:
        combos=make_combos(target, fixed, excluded, mode)
        return combos, [_combo_detail(c,st) for c in combos], st
    weights=_v34_weights(st, mode)
    for n in excluded_set: weights.pop(n,None)
    buckets={
        'hot':[n for n in st['hot'] if n in pool], 'mid':[n for n in st['mid'] if n in pool],
        'cold':[n for n in st['cold'] if n in pool], 'overdue':[n for n in st['overdue'] if n in pool], 'pool':pool,
    }
    plans = {
        'aggressive':['hot','overdue','cold','pool','pool','pool'],
        'conservative':['hot','mid','mid','pool','pool','pool'],
        'balanced':['hot','overdue','mid','cold','pool','pool'],
    }
    plan=plans.get(mode, plans['balanced'])
    candidates=[]; seen=set(); guard=0
    while len(candidates)<target*16 and guard<42000:
        guard+=1; combo=set(fixed_set)
        for name in plan:
            if len(combo)>=6: break
            pick=_v34_choice([n for n in buckets.get(name,pool) if n not in combo], weights)
            if pick: combo.add(pick)
        while len(combo)<6:
            pick=_v34_choice([n for n in pool if n not in combo], weights)
            if pick is None: break
            combo.add(pick)
        arr=tuple(sorted(combo))
        if len(arr)!=6 or arr in seen: continue
        seen.add(arr)
        odd=sum(n%2 for n in arr); total=sum(arr); zones=_v34_zones(arr); ac=_v34_ac(arr); cons=_v34_cons(arr); ends=len(set(n%10 for n in arr))
        if odd not in (2,3,4): continue
        if max(zones)>4 or min(zones)==0: continue
        if not (85<=total<=195): continue
        if not (4<=ac<=12): continue
        if cons>2 or ends<4: continue
        score=combo_score(arr,st)
        if score<78: continue
        candidates.append((score,list(arr)))
    candidates=sorted(candidates, key=lambda x:(-x[0], x[1]))
    combos=[]
    for score,c in candidates:
        # 회원 배포용으로 너무 비슷한 조합이 반복되지 않게 제한
        if all(_v34_similarity(c, old)<=3 for old in combos): combos.append(c)
        if len(combos)>=target: break
    if len(combos)<target:
        for _,c in candidates:
            if c not in combos: combos.append(c)
            if len(combos)>=target: break
    if len(combos)<target:
        for f in make_combos(target-len(combos), fixed, excluded, mode):
            if f not in combos: combos.append(f)
            if len(combos)>=target: break
    details=[_combo_detail(c,st) for c in combos[:target]]
    return combos[:target], details, st

def build_analysis_text(round_no, st, mode, fixed, excluded):
    hot=', '.join(map(str,st.get('hot',[])[:4])); overdue=', '.join(map(str,st.get('overdue',[])[:4])); cold=', '.join(map(str,st.get('cold',[])[:4]))
    mode_txt={'balanced':'균형형','conservative':'안정형','aggressive':'공격형'}.get(mode,'균형형')
    lines=[
        f'{round_no}회차는 V34 VIP AI 엔진 기준 {mode_txt}으로 분석했습니다.',
        f'최근 가중 핵심수는 {hot}번, 미출현 보강 후보는 {overdue}번 흐름이 강합니다.',
        f'저출현 변동 후보 {cold}번을 함께 반영해 과도한 HOT 편중을 줄였습니다.',
        '홀짝, 구간, 합계, AC값, 끝수, 연속수, 동반출현을 종합 필터링했습니다.'
    ]
    if fixed: lines.append(f'고정수 {fixed}번은 우선 반영하고 나머지 번호만 AI로 보정했습니다.')
    if excluded: lines.append(f'제외수 {excluded}번은 추천 후보에서 제외했습니다.')
    return '\n'.join(lines[:5])


# ===== V40 UPGRADE1 FINAL OVERRIDES: keep V34 UI, stabilize backend engine =====
def latest_stats(limit=100):
    """V40 Phase1 통계 엔진: 최근 10/30/50/100회 흐름, 미출현, 동반출현, 끝수/구간/홀짝/합계를 계산합니다."""
    with con() as c:
        rows = c.execute('SELECT * FROM draws ORDER BY round_no DESC LIMIT ?', (max(10, int(limit or 100)),)).fetchall()
    draws=[]
    for r in rows:
        nums=parse_nums(r['numbers'])
        if len(nums)==6:
            draws.append({'round_no':int(r['round_no']), 'draw_date':r['draw_date'] or '', 'numbers':nums, 'bonus':int(r['bonus'] or 0)})
    if not draws:
        draws=[{'round_no':r,'draw_date':d,'numbers':n,'bonus':b} for r,d,n,b in DEFAULT_DRAWS if len(n)==6]
    windows={10:draws[:10], 30:draws[:30], 50:draws[:50], 100:draws[:100]}
    freq_by_window={}
    for w,ds in windows.items():
        f={n:0 for n in range(1,46)}
        for d in ds:
            for n in d['numbers']:
                f[n]+=1
        freq_by_window[w]=f
    freq=freq_by_window[100]
    last_seen={n:999 for n in range(1,46)}
    for idx,d in enumerate(draws[:100]):
        for n in d['numbers']:
            if last_seen[n] == 999:
                last_seen[n]=idx
    pair_counts=collections.Counter()
    for d in draws[:100]:
        for a,b in itertools.combinations(d['numbers'],2):
            pair_counts[tuple(sorted((a,b)))] += 1
    end_counts={i:0 for i in range(10)}
    zone_counts={'1~15':0,'16~30':0,'31~45':0}
    odd_total=0; sums=[]
    for d in draws[:100]:
        sums.append(sum(d['numbers']))
        for n in d['numbers']:
            end_counts[n%10]+=1
            odd_total += n%2
            if n<=15: zone_counts['1~15']+=1
            elif n<=30: zone_counts['16~30']+=1
            else: zone_counts['31~45']+=1
    avg100=sum(freq.values())/45 if freq else 0
    hot=sorted(range(1,46), key=lambda n:(-(freq_by_window[30][n]*1.7 + freq_by_window[100][n]*0.7 + freq_by_window[10][n]*2.0), last_seen[n], n))[:12]
    cold=sorted(range(1,46), key=lambda n:(freq_by_window[100][n], -last_seen[n], n))[:12]
    overdue=sorted(range(1,46), key=lambda n:(last_seen[n], -freq_by_window[100][n], n), reverse=True)[:12]
    mid=sorted(range(1,46), key=lambda n:(abs(freq_by_window[100][n]-avg100), last_seen[n], n))[:15]
    top_pairs=[{'pair':list(p),'count':c} for p,c in pair_counts.most_common(12)]
    recent_numbers=set()
    for d in draws[:3]: recent_numbers.update(d['numbers'])
    return {
        'draws':draws,'freq':freq,'freq10':freq_by_window[10],'freq30':freq_by_window[30],'freq50':freq_by_window[50],'freq100':freq_by_window[100],
        'last_seen':last_seen,'hot':hot,'mid':mid,'cold':cold,'overdue':overdue,'top_pairs':top_pairs,'pair_counts':pair_counts,
        'end_counts':end_counts,'zone_counts':zone_counts,'odd_ratio':odd_total/(max(1,len(draws[:100])*6)),
        'sum_avg':round(sum(sums)/len(sums),1) if sums else 0,'recent_numbers':recent_numbers,
        'latest_round':draws[0]['round_no'] if draws else 1230
    }

def ac_value(combo):
    arr=sorted(combo)
    diffs={b-a for a,b in itertools.combinations(arr,2)}
    return max(0, len(diffs)-5)

def combo_score(combo, st):
    """0~100 AI 점수. 당첨 보장 점수가 아니라 통계 균형/분산 품질 점수입니다."""
    combo=sorted(parse_nums(combo));
    if len(combo)!=6: return 0
    f10,f30,f100=st['freq10'],st['freq30'],st['freq100']; last=st['last_seen']; pairs=st['pair_counts']
    total=sum(combo); odd=sum(n%2 for n in combo); even=6-odd
    zones=[sum(n<=15 for n in combo),sum(16<=n<=30 for n in combo),sum(n>=31 for n in combo)]
    cons=sum(1 for a,b in zip(combo,combo[1:]) if b-a==1)
    ends=len(set(n%10 for n in combo)); ac=ac_value(combo)
    # 기본 패턴 점수
    score=42.0
    score += {3:13,2:10,4:10,1:3,5:3,0:-8,6:-8}.get(odd,0)
    score += 13 if 105<=total<=175 else (8 if 95<=total<=190 else -10)
    score += 12 if max(zones)<=3 and min(zones)>=1 else (5 if max(zones)<=4 else -8)
    score += 7 if 5<=ac<=10 else (3 if 4<=ac<=11 else -4)
    score += 6 if ends>=5 else (3 if ends==4 else -4)
    score += 5 if cons<=1 else (-3 if cons==2 else -9)
    # 최근 흐름 점수: 과열수는 과하게 몰리지 않게, 중간/보강수를 같이 반영
    hot_hit=len(set(combo)&set(st['hot'][:10])); cold_hit=len(set(combo)&set(st['cold'][:10])); overdue_hit=len(set(combo)&set(st['overdue'][:10]))
    score += min(10, hot_hit*3.0) + min(7, cold_hit*2.1) + min(8, overdue_hit*2.2)
    if hot_hit>4: score -= 7
    if len(set(combo)&st['recent_numbers'])>=4: score -= 5
    # 동반출현은 1~3개 정도만 가산, 과도한 과거쌍 몰림은 감점
    pair_sum=sum(pairs.get(tuple(sorted((a,b))),0) for a,b in itertools.combinations(combo,2))
    strong_pairs=sum(1 for a,b in itertools.combinations(combo,2) if pairs.get(tuple(sorted((a,b))),0)>=4)
    score += min(10, pair_sum/4.0) + min(5, strong_pairs*1.5)
    if strong_pairs>5: score -= 5
    # 10/30/100 가중치 평균이 너무 한쪽으로 쏠리지 않게
    heat=sum(f10[n]*2.0 + f30[n]*1.1 + f100[n]*0.35 for n in combo)
    if 22 <= heat <= 55: score += 6
    elif heat > 70: score -= 8
    else: score += 2
    return round(max(35, min(99.7, score)), 1)

def tags_for_combo(combo, st):
    combo=sorted(combo); s=set(combo); tags=[]
    if len(s & set(st['hot'][:10]))>=2: tags.append('최근핵심')
    if len(s & set(st['overdue'][:10]))>=1: tags.append('미출현보강')
    if len(s & set(st['cold'][:10]))>=1: tags.append('저출현반등')
    if sum(n%2 for n in combo) in (2,3,4): tags.append('홀짝균형')
    zones=[sum(n<=15 for n in combo),sum(16<=n<=30 for n in combo),sum(n>=31 for n in combo)]
    if max(zones)<=3 and min(zones)>=1: tags.append('구간분산')
    if ac_value(combo) in range(5,11): tags.append('AC안정')
    pairs=st['pair_counts']
    if any(pairs.get(tuple(sorted((a,b))),0)>=4 for a,b in itertools.combinations(combo,2)): tags.append('동반출현')
    return tags[:5] or ['균형형']

def combo_detail(combo, st):
    combo=sorted(combo)
    odd=sum(n%2 for n in combo); zones=[sum(n<=15 for n in combo),sum(16<=n<=30 for n in combo),sum(n>=31 for n in combo)]
    pair_hits=[]
    for a,b in itertools.combinations(combo,2):
        cnt=st['pair_counts'].get(tuple(sorted((a,b))),0)
        if cnt>=3: pair_hits.append({'pair':[a,b], 'count':cnt})
    pair_hits=sorted(pair_hits, key=lambda x:-x['count'])[:3]
    return {'numbers':combo,'score':combo_score(combo,st),'tags':tags_for_combo(combo,st),'sum':sum(combo),'odd':odd,'even':6-odd,'zones':zones,'ac':ac_value(combo),'pair_hits':pair_hits}

def _weighted_pick(candidates, weights, k):
    picked=[]; pool=list(candidates); w=list(weights)
    for _ in range(min(k,len(pool))):
        total=sum(max(0.01,x) for x in w)
        r=random.random()*total; acc=0; idx=0
        for i,x in enumerate(w):
            acc += max(0.01,x)
            if acc>=r:
                idx=i; break
        picked.append(pool.pop(idx)); w.pop(idx)
    return picked

def make_premium_combos(count=10, fixed='', excluded='', mode='balanced'):
    st=latest_stats(120)
    fixed_set=set(parse_nums(fixed)); excluded_set=set(parse_nums(excluded))
    fixed_set={n for n in fixed_set if n not in excluded_set}
    if len(fixed_set)>6: fixed_set=set(sorted(fixed_set)[:6])
    pool=[n for n in range(1,46) if n not in excluded_set and n not in fixed_set]
    target=max(1,min(50,int(count or 10)))
    if len(pool)+len(fixed_set)<6:
        raise HTTPException(400, '고정수/제외수를 확인하세요. 선택 가능한 번호가 부족합니다.')
    past={tuple(d['numbers']) for d in st['draws']}
    f10,f30,f100,last=st['freq10'],st['freq30'],st['freq100'],st['last_seen']
    weights={}
    for n in pool:
        hot = f30[n]*1.4 + f10[n]*2.0 + f100[n]*0.35
        cold = max(0, 7-f100[n]) + min(8,last[n])*0.35
        mid = 6 - min(6, abs(f100[n] - (sum(f100.values())/45)))
        if mode=='aggressive': weights[n]=1 + hot*1.35 + cold*0.45 + mid*0.5
        elif mode=='conservative': weights[n]=1 + hot*0.65 + cold*1.25 + mid*0.9
        else: weights[n]=1 + hot*0.95 + cold*0.9 + mid*0.75
        # 직전 3회 과다 반영은 낮춤
        if n in st['recent_numbers']: weights[n]*=0.72
    candidates=[]; seen=set(); tries=0
    needed=max(target*75, 900)
    while len(candidates)<needed and tries<40000:
        tries+=1
        need=6-len(fixed_set)
        nums=set(fixed_set)
        picked=_weighted_pick(pool, [weights[n] for n in pool], need)
        nums.update(picked)
        arr=tuple(sorted(nums))
        if len(arr)!=6 or arr in seen or arr in past: continue
        odd=sum(n%2 for n in arr); total=sum(arr); zones=[sum(n<=15 for n in arr),sum(16<=n<=30 for n in arr),sum(n>=31 for n in arr)]
        cons=sum(1 for a,b in zip(arr,arr[1:]) if b-a==1)
        if odd not in (2,3,4): continue
        if not (90<=total<=195): continue
        if max(zones)>4 or 0 in zones: continue
        if cons>2: continue
        if len(set(n%10 for n in arr))<3: continue
        seen.add(arr)
        candidates.append((combo_score(arr,st), list(arr)))
    candidates=sorted(candidates, key=lambda x:(-x[0], x[1]))
    selected=[]
    for score, combo in candidates:
        # 최종 10개는 서로 너무 비슷하지 않게 분산
        if all(len(set(combo)&set(prev))<=4 for prev in selected):
            selected.append(combo)
        if len(selected)>=target: break
    if len(selected)<target:
        for score, combo in candidates:
            if combo not in selected:
                selected.append(combo)
            if len(selected)>=target: break
    details=[combo_detail(c, st) for c in selected[:target]]
    return selected[:target], details, st

def _engine_summary(details, st):
    if not details: return {'avg_score':0,'combo_count':0}
    scores=[d.get('score',0) for d in details]
    all_nums=[n for d in details for n in d.get('numbers',[])]
    freq=collections.Counter(all_nums)
    return {
        'avg_score':round(sum(scores)/len(scores),1),
        'max_score':max(scores),
        'combo_count':len(details),
        'latest_round':st.get('latest_round'),
        'hot':st.get('hot',[])[:8],
        'cold':st.get('cold',[])[:8],
        'overdue':st.get('overdue',[])[:8],
        'top_used':[n for n,_ in freq.most_common(8)],
        'top_pairs':st.get('top_pairs',[])[:5]
    }

def build_analysis_text(round_no, st, mode, fixed, excluded, details=None):
    """생성된 추천 조합과 실제 최근 100회 통계를 함께 사용해 매번 다른 4~5줄 분석을 만듭니다."""
    details=details or []
    engine=_engine_summary(details, st)
    top_scores=sorted(details, key=lambda x:-x.get('score',0))[:3]
    used_nums=engine.get('top_used',[])[:6]
    hot=[n for n in st.get('hot',[])[:10] if n in used_nums] or st.get('hot',[])[:4]
    overdue=[n for n in st.get('overdue',[])[:10] if n in used_nums] or st.get('overdue',[])[:4]
    cold=[n for n in st.get('cold',[])[:10] if n in used_nums] or st.get('cold',[])[:4]
    pair_text=', '.join([f"{p['pair'][0]}-{p['pair'][1]}({p['count']}회)" for p in st.get('top_pairs',[])[:3]]) or '동반출현 데이터 보강 중'
    best = top_scores[0] if top_scores else {}
    mode_name={'balanced':'균형형','conservative':'보강형','aggressive':'공격형'}.get(mode, mode or '균형형')
    variants=[
        f"{round_no}회차는 최근 10/30/100회 흐름을 합산해 {mode_name} 기준으로 재분석했습니다.",
        f"이번 생성은 직전 과열 흐름을 낮추고 최근 100회 누적 통계를 함께 반영했습니다.",
        f"{round_no}회차 분석은 출현빈도, 미출현 간격, 동반출현, AC값을 동시에 적용했습니다."
    ]
    line1=random.choice(variants)
    line2=random.choice([
        f"핵심 후보는 {', '.join(map(str,hot[:5]))}번이며, 미출현 보강 후보는 {', '.join(map(str,overdue[:5]))}번입니다.",
        f"최근 강한 흐름은 {', '.join(map(str,hot[:5]))}번, 저출현 반등 후보는 {', '.join(map(str,cold[:5]))}번 중심으로 잡았습니다.",
        f"번호 풀은 HOT {', '.join(map(str,hot[:4]))}번과 보강 {', '.join(map(str,overdue[:4]))}번을 섞어 구성했습니다."
    ])
    if best:
        line3=f"대표 조합은 합계 {best.get('sum')} / AC {best.get('ac')} / 홀짝 {best.get('odd')}:{best.get('even')} 기준이며 AI점수는 {best.get('score')}점입니다."
    else:
        line3=f"평균 AI점수는 {engine.get('avg_score',0)}점이며 과도한 중복과 구간 쏠림을 줄였습니다."
    line4=random.choice([
        f"동반출현 참고 흐름은 {pair_text}이며, 조합 간 중복을 낮춰 분산형으로 정리했습니다.",
        f"동반출현은 {pair_text} 흐름을 참고했고, 끝수와 구간이 한쪽으로 몰리지 않게 제한했습니다.",
        f"상위 동반 흐름({pair_text})은 참고만 하고, 동일 패턴 반복은 줄였습니다."
    ])
    line5=f"분석 갱신시각: {now()}"
    return '\n'.join([line1,line2,line3,line4,line5])

def build_sms(member_name, round_no, combos, analysis, details):
    name=member_name or '회원'
    best=sorted(details or [], key=lambda x:-x.get('score',0))[:1]
    best_line=''
    if best:
        b=best[0]
        best_line=f"대표 조합 포인트: 합계 {b.get('sum')} / AC {b.get('ac')} / 홀짝 {b.get('odd')}:{b.get('even')} / AI점수 {b.get('score')}점"
    return '\n'.join([
        f'안녕하세요 {name}님, BBLOTTO입니다.',
        f'{round_no}회차 추천번호와 이번 회차 분석을 안내드립니다.',
        '[추천번호]',
        *[f'{i+1}. '+', '.join(map(str,c)) for i,c in enumerate(combos)],
        '[분석요약]',
        analysis,
        best_line,
        '좋은 결과 있으시길 바랍니다.'
    ]).strip()



# ===== V40 UPGRADE1 DIVERSITY OVERRIDE =====
def make_premium_combos(count=10, fixed='', excluded='', mode='balanced'):
    st=latest_stats(120)
    fixed_set=set(parse_nums(fixed)); excluded_set=set(parse_nums(excluded))
    fixed_set={n for n in fixed_set if n not in excluded_set}
    if len(fixed_set)>6: fixed_set=set(sorted(fixed_set)[:6])
    pool=[n for n in range(1,46) if n not in excluded_set and n not in fixed_set]
    target=max(1,min(50,int(count or 10)))
    if len(pool)+len(fixed_set)<6:
        raise HTTPException(400, '고정수/제외수를 확인하세요. 선택 가능한 번호가 부족합니다.')
    past={tuple(d['numbers']) for d in st['draws']}
    f10,f30,f100,last=st['freq10'],st['freq30'],st['freq100'],st['last_seen']
    avg100=sum(f100.values())/45
    weights={}
    for n in pool:
        hot = f30[n]*1.0 + f10[n]*1.7 + f100[n]*0.20
        cold = max(0, avg100-f100[n]) + min(10,last[n])*0.40
        mid = max(0, 6 - abs(f100[n]-avg100))
        if mode=='aggressive': w=1 + hot*1.15 + cold*0.55 + mid*0.45
        elif mode=='conservative': w=1 + hot*0.55 + cold*1.30 + mid*0.85
        else: w=1 + hot*0.75 + cold*1.05 + mid*0.70
        if n in st['recent_numbers']: w*=0.62
        weights[n]=max(0.2,w)
    candidates=[]; seen=set(); tries=0
    needed=max(target*140, 1600)
    while len(candidates)<needed and tries<60000:
        tries+=1
        nums=set(fixed_set)
        # 조합별 시드 다양화: HOT/COLD/MID/OVERDUE 비율을 랜덤으로 섞음
        buckets=[]
        if mode=='aggressive': buckets=[st['hot'][:14], st['overdue'][:14], pool, pool, pool, pool]
        elif mode=='conservative': buckets=[st['mid'][:16], st['cold'][:14], st['overdue'][:14], pool, pool, pool]
        else: buckets=[st['hot'][:12], st['mid'][:15], st['cold'][:12], st['overdue'][:12], pool, pool]
        random.shuffle(buckets)
        for bucket in buckets:
            if len(nums)>=6: break
            usable=[n for n in bucket if n in pool and n not in nums]
            if usable:
                nums.update(_weighted_pick(usable, [weights[n] for n in usable], 1))
        while len(nums)<6:
            usable=[n for n in pool if n not in nums]
            nums.update(_weighted_pick(usable, [weights[n] for n in usable], 1))
        arr=tuple(sorted(nums))
        if len(arr)!=6 or arr in seen or arr in past: continue
        odd=sum(n%2 for n in arr); total=sum(arr); zones=[sum(n<=15 for n in arr),sum(16<=n<=30 for n in arr),sum(n>=31 for n in arr)]
        cons=sum(1 for a,b in zip(arr,arr[1:]) if b-a==1)
        if odd not in (2,3,4): continue
        if not (90<=total<=195): continue
        if max(zones)>4 or 0 in zones: continue
        if cons>2: continue
        if len(set(n%10 for n in arr))<4: continue
        seen.add(arr)
        candidates.append((combo_score(arr,st), list(arr)))
    candidates=sorted(candidates, key=lambda x:(-x[0], x[1]))
    selected=[]; usage=collections.Counter()
    # 1차: 조합 간 겹침과 특정 숫자 과사용 제한
    for score, combo in candidates:
        if any(usage[n]>=3 for n in combo if n not in fixed_set):
            continue
        if all(len(set(combo)&set(prev))<=3 for prev in selected):
            selected.append(combo); usage.update(combo)
        if len(selected)>=target: break
    # 2차: 부족할 때 조건 완화
    if len(selected)<target:
        for score, combo in candidates:
            if combo in selected: continue
            if any(usage[n]>=4 for n in combo if n not in fixed_set):
                continue
            if all(len(set(combo)&set(prev))<=4 for prev in selected):
                selected.append(combo); usage.update(combo)
            if len(selected)>=target: break
    # 3차: 그래도 부족하면 순위대로 보충
    if len(selected)<target:
        for score, combo in candidates:
            if combo not in selected:
                selected.append(combo); usage.update(combo)
            if len(selected)>=target: break
    details=[combo_detail(c, st) for c in selected[:target]]
    return selected[:target], details, st

# ===== V40 UPGRADE1 FINAL DIVERSITY STRICT =====
def make_premium_combos(count=10, fixed='', excluded='', mode='balanced'):
    st=latest_stats(120)
    fixed_set=set(parse_nums(fixed)); excluded_set=set(parse_nums(excluded))
    fixed_set={n for n in fixed_set if n not in excluded_set}
    if len(fixed_set)>6: fixed_set=set(sorted(fixed_set)[:6])
    pool=[n for n in range(1,46) if n not in excluded_set and n not in fixed_set]
    target=max(1,min(50,int(count or 10)))
    if len(pool)+len(fixed_set)<6:
        raise HTTPException(400, '고정수/제외수를 확인하세요. 선택 가능한 번호가 부족합니다.')
    past={tuple(d['numbers']) for d in st['draws']}
    f10,f30,f100,last=st['freq10'],st['freq30'],st['freq100'],st['last_seen']
    avg100=sum(f100.values())/45
    weights={}
    for n in pool:
        hot = f30[n]*0.85 + f10[n]*1.40 + f100[n]*0.18
        cold = max(0, avg100-f100[n]) + min(10,last[n])*0.38
        mid = max(0, 6 - abs(f100[n]-avg100))
        if mode=='aggressive': w=1 + hot*1.05 + cold*0.65 + mid*0.45
        elif mode=='conservative': w=1 + hot*0.50 + cold*1.25 + mid*0.90
        else: w=1 + hot*0.70 + cold*1.00 + mid*0.80
        if n in st['recent_numbers']: w*=0.58
        weights[n]=max(0.2,w)
    candidates=[]; seen=set(); tries=0; needed=max(target*180, 2200)
    while len(candidates)<needed and tries<80000:
        tries+=1; nums=set(fixed_set)
        if mode=='aggressive': buckets=[st['hot'][:14], st['overdue'][:14], st['mid'][:15], pool, pool, pool]
        elif mode=='conservative': buckets=[st['mid'][:16], st['cold'][:14], st['overdue'][:14], pool, pool, pool]
        else: buckets=[st['hot'][:12], st['mid'][:15], st['cold'][:12], st['overdue'][:12], pool, pool]
        random.shuffle(buckets)
        for bucket in buckets:
            if len(nums)>=6: break
            usable=[n for n in bucket if n in pool and n not in nums]
            if usable: nums.update(_weighted_pick(usable, [weights[n] for n in usable], 1))
        while len(nums)<6:
            usable=[n for n in pool if n not in nums]
            nums.update(_weighted_pick(usable, [weights[n] for n in usable], 1))
        arr=tuple(sorted(nums))
        if len(arr)!=6 or arr in seen or arr in past: continue
        odd=sum(n%2 for n in arr); total=sum(arr); zones=[sum(n<=15 for n in arr),sum(16<=n<=30 for n in arr),sum(n>=31 for n in arr)]
        cons=sum(1 for a,b in zip(arr,arr[1:]) if b-a==1)
        if odd not in (2,3,4): continue
        if not (92<=total<=190): continue
        if max(zones)>4 or 0 in zones: continue
        if cons>1: continue
        if len(set(n%10 for n in arr))<4: continue
        seen.add(arr); candidates.append((combo_score(arr,st), list(arr)))
    candidates=sorted(candidates, key=lambda x:(-x[0], x[1]))
    selected=[]; usage=collections.Counter(); pair_usage=collections.Counter()
    for score, combo in candidates:
        pairs=[tuple(sorted(p)) for p in itertools.combinations(combo,2)]
        if any(usage[n]>=3 for n in combo if n not in fixed_set): continue
        if any(pair_usage[p]>=1 for p in pairs): continue
        if all(len(set(combo)&set(prev))<=3 for prev in selected):
            selected.append(combo); usage.update(combo); pair_usage.update(pairs)
        if len(selected)>=target: break
    if len(selected)<target:
        for score, combo in candidates:
            if combo in selected: continue
            pairs=[tuple(sorted(p)) for p in itertools.combinations(combo,2)]
            if any(usage[n]>=4 for n in combo if n not in fixed_set): continue
            if any(pair_usage[p]>=2 for p in pairs): continue
            if all(len(set(combo)&set(prev))<=4 for prev in selected):
                selected.append(combo); usage.update(combo); pair_usage.update(pairs)
            if len(selected)>=target: break
    if len(selected)<target:
        for score, combo in candidates:
            if combo not in selected:
                selected.append(combo)
            if len(selected)>=target: break
    details=[combo_detail(c, st) for c in selected[:target]]
    return selected[:target], details, st

# ===== V40 UPGRADE1 SCORE CALIBRATION =====
def combo_score(combo, st):
    combo=sorted(parse_nums(combo))
    if len(combo)!=6: return 0
    f10,f30,f100=st['freq10'],st['freq30'],st['freq100']; last=st['last_seen']; pairs=st['pair_counts']
    total=sum(combo); odd=sum(n%2 for n in combo)
    zones=[sum(n<=15 for n in combo),sum(16<=n<=30 for n in combo),sum(n>=31 for n in combo)]
    cons=sum(1 for a,b in zip(combo,combo[1:]) if b-a==1); ends=len(set(n%10 for n in combo)); ac=ac_value(combo)
    score=58.0
    score += {3:9,2:7,4:7,1:1,5:1,0:-7,6:-7}.get(odd,0)
    score += 9 if 105<=total<=175 else (5 if 92<=total<=190 else -8)
    score += 8 if max(zones)<=3 and min(zones)>=1 else (3 if max(zones)<=4 and min(zones)>=1 else -7)
    score += 6 if 5<=ac<=10 else (2 if 4<=ac<=12 else -4)
    score += 4 if ends>=5 else (2 if ends==4 else -3)
    score += 4 if cons==0 else (2 if cons==1 else -5)
    hot_hit=len(set(combo)&set(st['hot'][:10])); cold_hit=len(set(combo)&set(st['cold'][:10])); overdue_hit=len(set(combo)&set(st['overdue'][:10]))
    score += min(7, hot_hit*1.6) + min(6, cold_hit*1.5) + min(6, overdue_hit*1.5)
    if hot_hit>4: score -= 5
    pair_sum=sum(pairs.get(tuple(sorted((a,b))),0) for a,b in itertools.combinations(combo,2))
    strong_pairs=sum(1 for a,b in itertools.combinations(combo,2) if pairs.get(tuple(sorted((a,b))),0)>=4)
    score += min(6, pair_sum/8.0) + min(4, strong_pairs*1.0)
    heat=sum(f10[n]*1.6 + f30[n]*0.8 + f100[n]*0.18 for n in combo)
    if 16 <= heat <= 48: score += 4
    elif heat > 65: score -= 5
    # 작은 분산값을 넣어 모든 조합이 같은 점수로 보이지 않게 함
    score += ((sum(n*n for n in combo) % 13) - 6) * 0.15
    return round(max(60, min(96.8, score)), 1)

# ===== V40 UPGRADE1 SCORE CALIBRATION 2 =====
def combo_score(combo, st):
    combo=sorted(parse_nums(combo))
    if len(combo)!=6: return 0
    f10,f30,f100=st['freq10'],st['freq30'],st['freq100']; last=st['last_seen']; pairs=st['pair_counts']
    total=sum(combo); odd=sum(n%2 for n in combo)
    zones=[sum(n<=15 for n in combo),sum(16<=n<=30 for n in combo),sum(n>=31 for n in combo)]
    cons=sum(1 for a,b in zip(combo,combo[1:]) if b-a==1); ends=len(set(n%10 for n in combo)); ac=ac_value(combo)
    score=50.0
    score += {3:8,2:6,4:6,1:0,5:0,0:-8,6:-8}.get(odd,0)
    score += 8 if 110<=total<=170 else (4 if 95<=total<=190 else -8)
    score += 7 if max(zones)<=3 and min(zones)>=1 else (2 if max(zones)<=4 and min(zones)>=1 else -6)
    score += 5 if 5<=ac<=10 else (2 if 4<=ac<=12 else -4)
    score += 3 if ends>=5 else (1 if ends==4 else -3)
    score += 3 if cons==0 else (1 if cons==1 else -5)
    hot_hit=len(set(combo)&set(st['hot'][:10])); cold_hit=len(set(combo)&set(st['cold'][:10])); overdue_hit=len(set(combo)&set(st['overdue'][:10]))
    score += min(6, hot_hit*1.3) + min(5, cold_hit*1.2) + min(5, overdue_hit*1.2)
    pair_sum=sum(pairs.get(tuple(sorted((a,b))),0) for a,b in itertools.combinations(combo,2))
    strong_pairs=sum(1 for a,b in itertools.combinations(combo,2) if pairs.get(tuple(sorted((a,b))),0)>=4)
    score += min(5, pair_sum/10.0) + min(3, strong_pairs*0.8)
    heat=sum(f10[n]*1.5 + f30[n]*0.7 + f100[n]*0.15 for n in combo)
    if 15 <= heat <= 45: score += 3
    elif heat > 62: score -= 5
    # 번호별 분산 보정
    score += ((sum(n*n for n in combo) % 17) - 8) * 0.18
    return round(max(65, min(94.9, score)), 1)

# ===== PATCH 023: BBLOTTO AI ENGINE V1 INSTALL =====
# RC8-2: 기존 recommend_engine_v1 설치 훅 제거. 추천번호 생성은 하단 AI V4 make_premium_combos()만 사용합니다.


# ===== RC2 SPRINT 2-3: AI ENGINE V2 + DASHBOARD INSIGHT PATCH =====
SPRINT23_ENGINE_VERSION = 'BBLOTTO_PRO_V2_STABLE_RC3_12'

def ensure_sprint23_schema():
    """추천 엔진 실행 이력/대시보드 캐시용 테이블을 안전하게 준비합니다."""
    try:
        with con() as c:
            c.execute('CREATE TABLE IF NOT EXISTS engine_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, recommendation_id INTEGER DEFAULT 0, round_no INTEGER DEFAULT 0, member_id INTEGER DEFAULT 0, mode TEXT DEFAULT "balanced", count INTEGER DEFAULT 0, candidate_count INTEGER DEFAULT 0, selected_count INTEGER DEFAULT 0, avg_score REAL DEFAULT 0, max_score REAL DEFAULT 0, min_score REAL DEFAULT 0, engine_version TEXT DEFAULT "", created_by INTEGER DEFAULT 0, created_at TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS dashboard_snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_json TEXT DEFAULT "{}", created_at TEXT)')
            c.commit()
    except Exception:
        pass

ensure_sprint23_schema()

def _s23_weighted_number_profile(st, mode='balanced'):
    f10,f30,f50,f100=st.get('freq10',{}),st.get('freq30',{}),st.get('freq50',{}),st.get('freq100',{})
    last=st.get('last_seen',{})
    avg100=(sum(f100.values())/45) if f100 else 0
    recent=set(st.get('recent_numbers',set()) or set())
    profile={}
    for n in range(1,46):
        hot=f10.get(n,0)*2.15 + f30.get(n,0)*1.15 + f50.get(n,0)*0.72 + f100.get(n,0)*0.35
        cold=max(0, avg100-f100.get(n,0))*0.85 + min(30,last.get(n,999))*0.11
        balance=max(0, 5.5-abs(f100.get(n,0)-avg100))*0.55
        pair_boost=0
        for k,v in (st.get('pair_counts') or {}).items():
            try:
                if n in k: pair_boost += min(4, v)*0.03
            except Exception:
                pass
        if mode=='aggressive': score=hot*1.18 + cold*0.55 + balance*0.52 + pair_boost
        elif mode=='conservative': score=hot*0.62 + cold*1.25 + balance*0.88 + pair_boost
        else: score=hot*0.83 + cold*1.03 + balance*0.75 + pair_boost
        if n in recent:
            score*=0.70
        profile[n]=round(max(0.25, score+1),4)
    return profile

def s23_combo_score(combo, st, mode='balanced'):
    combo=sorted(parse_nums(combo))
    if len(combo)!=6: return 0
    f10,f30,f50,f100=st.get('freq10',{}),st.get('freq30',{}),st.get('freq50',{}),st.get('freq100',{})
    last=st.get('last_seen',{})
    pairs=st.get('pair_counts') or {}
    total=sum(combo); odd=sum(n%2 for n in combo)
    zones=[sum(n<=15 for n in combo),sum(16<=n<=30 for n in combo),sum(n>=31 for n in combo)]
    cons=sum(1 for a,b in zip(combo,combo[1:]) if b-a==1)
    ends=len(set(n%10 for n in combo)); ac=ac_value(combo)
    score=52.0
    score += {3:9.0,2:7.0,4:7.0,1:1.0,5:1.0,0:-8.0,6:-8.0}.get(odd,0)
    score += 9 if 105<=total<=175 else (5 if 92<=total<=190 else -9)
    score += 8 if max(zones)<=3 and min(zones)>=1 else (3 if max(zones)<=4 and min(zones)>=1 else -8)
    score += 6 if 5<=ac<=10 else (2 if 4<=ac<=12 else -5)
    score += 5 if ends>=5 else (2 if ends==4 else -4)
    score += 4 if cons==0 else (1.5 if cons==1 else -6)
    hot_hit=len(set(combo)&set(st.get('hot',[])[:12])); cold_hit=len(set(combo)&set(st.get('cold',[])[:12])); overdue_hit=len(set(combo)&set(st.get('overdue',[])[:12]))
    score += min(7,hot_hit*1.25)+min(6,cold_hit*1.15)+min(6,overdue_hit*1.15)
    if hot_hit>=5: score-=4
    pair_sum=sum(pairs.get(tuple(sorted((a,b))),0) for a,b in itertools.combinations(combo,2))
    score += min(6.5, pair_sum/9.0)
    heat=sum(f10.get(n,0)*1.8 + f30.get(n,0)*0.85 + f50.get(n,0)*0.42 + f100.get(n,0)*0.17 for n in combo)
    if 16<=heat<=52: score+=4
    elif heat>68: score-=5
    # V2: 최근 100회에서 너무 흔한 번호만 몰리는 조합 감점, 오래된 번호 보완 가점
    avg100=(sum(f100.values())/45) if f100 else 0
    above=sum(1 for n in combo if f100.get(n,0)>avg100+2)
    overdue=sum(1 for n in combo if last.get(n,0)>=10)
    if above>=5: score-=4
    if 1<=overdue<=3: score+=3
    # 동일 10번대 쏠림 완화
    decades=collections.Counter((n-1)//10 for n in combo)
    if max(decades.values())>=4: score-=5
    # 안정적이지만 같은 점수 반복 방지
    score += ((sum(n*n for n in combo) % 19)-9)*0.13
    return round(max(67.0, min(96.3, score)),1)

def make_premium_combos(count=10, fixed='', excluded='', mode='balanced'):
    """RC2 Sprint 2-3 V2 엔진: 후보 확장, 포트폴리오 분산, 점수 기반 선별."""
    st=latest_stats(120)
    fixed_set=set(parse_nums(fixed)); excluded_set=set(parse_nums(excluded))
    fixed_set={n for n in fixed_set if n not in excluded_set}
    if len(fixed_set)>6: fixed_set=set(sorted(fixed_set)[:6])
    pool=[n for n in range(1,46) if n not in excluded_set and n not in fixed_set]
    target=max(1,min(50,int(count or 10)))
    if len(pool)+len(fixed_set)<6:
        raise HTTPException(400, '고정수/제외수를 확인하세요. 선택 가능한 번호가 부족합니다.')
    profile=_s23_weighted_number_profile(st, mode)
    past={tuple(d['numbers']) for d in st.get('draws',[])}
    buckets={
        'hot':[n for n in st.get('hot',[])[:18] if n in pool],
        'cold':[n for n in st.get('cold',[])[:18] if n in pool],
        'overdue':[n for n in st.get('overdue',[])[:18] if n in pool],
        'mid':[n for n in st.get('mid',[])[:18] if n in pool],
        'all':pool[:]
    }
    if mode=='aggressive': plan=['hot','hot','mid','overdue','all','all']
    elif mode=='conservative': plan=['cold','overdue','mid','mid','all','all']
    else: plan=['hot','cold','overdue','mid','all','all']
    needed=max(2600,target*240)
    candidates=[]; seen=set(); attempts=0
    while len(candidates)<needed and attempts<95000:
        attempts+=1
        nums=set(fixed_set)
        p=plan[:]; random.shuffle(p)
        for b in p:
            if len(nums)>=6: break
            usable=[n for n in buckets.get(b, pool) if n not in nums]
            if usable:
                nums.update(_weighted_pick(usable, [profile[n] for n in usable], 1))
        while len(nums)<6:
            usable=[n for n in pool if n not in nums]
            nums.update(_weighted_pick(usable, [profile[n] for n in usable], 1))
        arr=tuple(sorted(nums))
        if len(arr)!=6 or arr in seen or arr in past: continue
        odd=sum(n%2 for n in arr); total=sum(arr); zones=[sum(n<=15 for n in arr),sum(16<=n<=30 for n in arr),sum(n>=31 for n in arr)]
        cons=sum(1 for a,b in zip(arr,arr[1:]) if b-a==1)
        if odd not in (2,3,4): continue
        if not (92<=total<=190): continue
        if max(zones)>4 or min(zones)==0: continue
        if cons>1: continue
        if len(set(n%10 for n in arr))<4: continue
        seen.add(arr)
        candidates.append((s23_combo_score(arr,st,mode), list(arr)))
    candidates=sorted(candidates,key=lambda x:(-x[0], x[1]))
    selected=[]; usage=collections.Counter(); pair_usage=collections.Counter()
    for score, combo in candidates:
        pairs=[tuple(sorted(p)) for p in itertools.combinations(combo,2)]
        if any(usage[n]>=3 for n in combo if n not in fixed_set): continue
        if any(pair_usage[p]>=1 for p in pairs): continue
        if all(len(set(combo)&set(prev))<=3 for prev in selected):
            selected.append(combo); usage.update(combo); pair_usage.update(pairs)
        if len(selected)>=target: break
    if len(selected)<target:
        for score, combo in candidates:
            if combo in selected: continue
            pairs=[tuple(sorted(p)) for p in itertools.combinations(combo,2)]
            if any(usage[n]>=4 for n in combo if n not in fixed_set): continue
            if any(pair_usage[p]>=2 for p in pairs): continue
            if all(len(set(combo)&set(prev))<=4 for prev in selected):
                selected.append(combo); usage.update(combo); pair_usage.update(pairs)
            if len(selected)>=target: break
    if len(selected)<target:
        for score, combo in candidates:
            if combo not in selected:
                selected.append(combo)
            if len(selected)>=target: break
    details=[]
    for ccc in selected[:target]:
        d=combo_detail(ccc, st)
        d['score']=s23_combo_score(ccc,st,mode)
        d['engine_version']=SPRINT23_ENGINE_VERSION
        d['v2_reason']='최근 10/30/50/100회 가중치, 미출현 보정, 동반출현, 포트폴리오 분산을 반영했습니다.'
        details.append(d)
    st['s23_candidates']=len(candidates)
    return selected[:target], details, st

def _engine_summary(details, st):
    scores=[float(d.get('score') or d.get('ai_score') or d.get('vip_score') or 0) for d in (details or []) if (d.get('score') or d.get('ai_score') or d.get('vip_score'))]
    return {
        'version': SPRINT23_ENGINE_VERSION,
        'engine_version': SPRINT23_ENGINE_VERSION,
        'avg_score': round(sum(scores)/len(scores),1) if scores else 0,
        'max_score': round(max(scores),1) if scores else 0,
        'min_score': round(min(scores),1) if scores else 0,
        'candidate_count': int(st.get('s23_candidates') or 0),
        'selected_count': len(details or []),
        'latest_round': st.get('latest_round') or 0,
        'v2_pipeline_report': {
            'pipeline':'최근 100회 통계 → 번호별 V2 가중치 → 후보 확장 → 패턴 필터 → 포트폴리오 분산 → 최종 선별',
            'stage1_candidates': int(st.get('s23_candidates') or 0),
            'stage2_filters':'홀짝/합계/구간/AC/끝수/연속수',
            'stage3_portfolio':'숫자 과사용·중복 페어 제한',
            'summary':'RC2 Sprint 2-3 V2 엔진으로 후보 수와 분산 품질을 함께 강화했습니다.'
        }
    }

