import random
from .ai_engine import analytics, ac_value, section_count, odd_even, consecutive_count


def analyze(sets):
    a = analytics()
    first = sets[0] if sets else []
    odd, even = odd_even(first)
    sec = section_count(first)
    ac = ac_value(first) if first else 0
    cons = consecutive_count(first) if first else 0
    strong_section_idx = a["sections30"].index(max(a["sections30"]))
    strong_section = ["저번대(1~15)", "중번대(16~30)", "고번대(31~45)"][strong_section_idx]
    hot = ', '.join(map(str, a['hot'][:5]))
    cold = ', '.join(map(str, a['cold'][:5]))
    templates = [
        f"최근 30회 흐름에서는 {strong_section} 출현 비중이 비교적 높게 나타나며, 핵심수는 {hot}번 중심으로 확인됩니다.",
        f"이번 조합은 강세 번호({hot})와 변동 후보({cold})를 함께 반영해 안정성과 변동성을 같이 고려했습니다.",
        f"첫 조합 기준 홀짝은 {odd}:{even}, 구간은 1~15({sec[0]}) / 16~30({sec[1]}) / 31~45({sec[2]}) 구조입니다.",
        f"AC값은 {ac}, 연속수는 {cons}쌍으로 과한 몰림을 줄이고 번호 간격을 자연스럽게 맞췄습니다.",
        f"최근 30회 평균 합계는 약 {a['avg_sum30']}선이며, 이번 추천도 과도한 저합계·고합계를 피하는 방향으로 구성했습니다.",
    ]
    random.shuffle(templates)
    return "\n".join(templates[:3])


def make_sms(round_no, sets, analysis, greeting, member_name=""):
    name_line = f"{member_name} 회원님," if member_name else "안녕하세요."
    lines = [greeting.strip() or name_line, '', f'{round_no}회 추천번호 전달드립니다.', '']
    for i, s in enumerate(sets, 1):
        lines.append(f'{i}. ' + ' / '.join(map(str, s)))
    lines += ['', '[이번 회차 분석]', analysis, '', '', '좋은 결과 있으시길 바랍니다.']
    return '\n'.join(lines)
