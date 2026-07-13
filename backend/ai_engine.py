import random
from collections import Counter
from .draw_service import get_draws as db_get_draws


def get_draws(limit=None):
    return db_get_draws(limit)


def flatten(draws):
    nums=[]
    for d in draws:
        nums.extend(d["n"])
    return nums


def frequency(draws=None):
    draws = draws or get_draws()
    c = Counter(flatten(draws))
    return {n: c.get(n, 0) for n in range(1, 46)}


def section_count(nums):
    return [sum(n <= 15 for n in nums), sum(16 <= n <= 30 for n in nums), sum(n >= 31 for n in nums)]


def odd_even(nums):
    odd = sum(n % 2 == 1 for n in nums)
    return [odd, len(nums) - odd]


def end_digit_count(draws=None):
    cnt = Counter(n % 10 for n in flatten(draws or get_draws()))
    return {str(k): cnt.get(k, 0) for k in range(10)}


def consecutive_count(nums):
    nums=sorted(nums)
    return sum(1 for i in range(1, len(nums)) if nums[i] == nums[i-1] + 1)


def ac_value(nums):
    nums=sorted(nums)
    diffs=set()
    for i,a in enumerate(nums):
        for b in nums[i+1:]:
            diffs.add(abs(b-a))
    return max(0, len(diffs) - (len(nums)-1))


def number_gap_score(nums):
    nums=sorted(nums)
    gaps=[nums[i]-nums[i-1] for i in range(1,len(nums))]
    # too many adjacent or too wide gaps are penalized
    penalty=sum(1 for g in gaps if g <= 1) + sum(1 for g in gaps if g >= 16)
    return max(0, 6 - penalty)


def rank_numbers():
    f100=frequency(get_draws(100))
    f30=frequency(get_draws(30))
    f10=frequency(get_draws(10))
    latest_nums=set(get_draws(1)[0]["n"])
    scores={}
    for n in range(1,46):
        score = f100[n]*1.0 + f30[n]*1.35 + f10[n]*1.8
        if n in latest_nums:
            score -= 1.2  # 직전회차 과도 반영 방지
        if n <= 10 or n >= 41:
            score += 0.2
        scores[n]=round(score,3)
    hot=sorted(range(1,46), key=lambda x:(-scores[x], x))
    cold=sorted(range(1,46), key=lambda x:(scores[x], x))
    return scores, hot, cold


def build_weights(mode="balanced"):
    scores, hot, cold = rank_numbers()
    weights={}
    for n in range(1,46):
        w=1.0 + scores[n]/9
        if n in hot[:10]: w += 1.4
        if n in cold[:10]: w += 0.8
        if mode == "conservative":
            if 11 <= n <= 35: w += 0.9
            if n in hot[:15]: w += 0.5
        elif mode == "aggressive":
            if n <= 10 or n >= 31: w += 0.8
            if n in cold[:15]: w += 0.7
        else:
            if 16 <= n <= 35: w += 0.7
        weights[n]=max(w,0.25)
    return weights


def weighted_pick(weights):
    total=sum(weights.values())
    roll=random.random()*total
    for n,w in weights.items():
        roll-=w
        if roll <= 0:
            return n
    return 45


def set_quality(nums):
    nums=sorted(nums)
    odd, even = odd_even(nums)
    sec = section_count(nums)
    total=sum(nums)
    ac=ac_value(nums)
    cons=consecutive_count(nums)
    score=100
    if odd not in (2,3,4): score -= 22
    if max(sec) > 3: score -= 18
    if min(sec) == 0: score -= 12
    if total < 95 or total > 180: score -= 20
    if not (5 <= ac <= 10): score -= 14
    if cons > 2: score -= 10
    score += number_gap_score(nums)
    return score


def valid(nums):
    return set_quality(nums) >= 78


def normalize_user_numbers(values):
    nums=[]
    for n in values or []:
        try:
            x=int(n)
            if 1 <= x <= 45 and x not in nums:
                nums.append(x)
        except Exception:
            pass
    return nums[:6]


def generate_one(mode="balanced", fixed=None, exclude=None):
    fixed=normalize_user_numbers(fixed)
    exclude=set(normalize_user_numbers(exclude)) - set(fixed)
    weights=build_weights(mode)
    for x in exclude:
        weights.pop(x, None)
    if len(fixed) > 6:
        fixed=fixed[:6]
    available=[n for n in range(1,46) if n not in exclude and n not in fixed]
    for _ in range(500):
        selected=set(fixed)
        while len(selected)<6:
            selected.add(weighted_pick(weights))
        nums=sorted(selected)
        if len(nums)==6 and not (set(nums) & exclude) and valid(nums):
            return nums
    fallback=set(fixed)
    while len(fallback)<6 and available:
        fallback.add(random.choice(available))
    return sorted(fallback)[:6]


def generate_sets(count=10, mode="balanced", fixed=None, exclude=None):
    count=max(1,min(int(count),50))
    result=[]; seen=set(); guard=0
    while len(result)<count and guard<12000:
        guard+=1
        nums=generate_one(mode, fixed=fixed, exclude=exclude)
        key='-'.join(map(str,nums))
        if key not in seen:
            seen.add(key); result.append(nums)
    return result


def analytics():
    scores, hot, cold = rank_numbers()
    f100=frequency(get_draws(100)); f30=frequency(get_draws(30)); f10=frequency(get_draws(10))
    recent10=flatten(get_draws(10)); recent30=flatten(get_draws(30)); allnums=flatten(get_draws(100))
    acs=[ac_value(d['n']) for d in get_draws(30)]
    sums=[sum(d['n']) for d in get_draws(30)]
    return {
        "latest": get_draws(1)[0],
        "next_round": get_draws(1)[0]["r"] + 1,
        "draw_count": len(get_draws()),
        "recent": get_draws(10),
        "hot": hot[:12],
        "cold": cold[:12],
        "frequency100": f100,
        "frequency30": f30,
        "frequency10": f10,
        "sections10": section_count(recent10),
        "sections30": section_count(recent30),
        "sections100": section_count(allnums),
        "odd_even10": odd_even(recent10),
        "odd_even30": odd_even(recent30),
        "end_digits30": end_digit_count(get_draws(30)),
        "avg_ac30": round(sum(acs)/len(acs),1),
        "avg_sum30": round(sum(sums)/len(sums),1),
    }


def stats():
    a=analytics()
    return {"hot":a["hot"][:8], "cold":a["cold"][:8], "latest":a["latest"], "recent":a["recent"]}
