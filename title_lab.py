import re

CLICKBAIT = [
    r'100\s*%', r'гарант', r'самый лучший', r'точно лучший', r'никогда', r'всегда',
    r'вы не поверите', r'шок', r'сенсац', r'секрет,? который', r'взорвал интернет',
]
USEFUL = [
    'как', 'стоит', 'почему', 'сколько', 'ошиб', 'расход', 'ремонт', 'провер',
    'купить', 'сравн', 'переплат', 'выбрать', 'что проверить', 'на что смотреть',
]


def score_title(title, category=''):
    if not isinstance(title, str):
        return 0.0
    t = re.sub(r'\s+', ' ', title).strip()
    if not t:
        return 0.0

    score = 50.0
    n = len(t)
    if 45 <= n <= 90:
        score += 22
    elif 35 <= n <= 105:
        score += 10
    else:
        score -= 18

    lower = t.lower()
    if any(token in lower for token in USEFUL):
        score += 12
    if re.search(r'[:—-]', t):
        score += 3
    if '?' in t and t.count('?') == 1:
        score += 3
    if re.search(r'\b(что|как|когда|почему|стоит ли|какие)\b', lower):
        score += 5

    for pattern in CLICKBAIT:
        if re.search(pattern, lower, re.I):
            score -= 30
    if re.search(r'[!?]{2,}|\.{3,}', t):
        score -= 15
    if t.isupper():
        score -= 20
    if len(re.findall(r'\d+', t)) >= 3:
        score -= 8
    if re.search(r'\b(лучший|идеальный|безошибочн|навсегда)\b', lower):
        score -= 10

    # Category wording is not required; forcing it often makes headlines mechanical.
    if category and category.lower() in lower:
        score += 1

    return round(max(0, min(100, score)), 2)


def rank_titles(candidates, category=''):
    out = []
    seen = set()
    for title in candidates or []:
        if not isinstance(title, str):
            continue
        clean = re.sub(r'\s+', ' ', title).strip()
        key = re.sub(r'\W+', ' ', clean.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({'title': clean, 'score': score_title(clean, category)})
    return sorted(out, key=lambda x: x['score'], reverse=True)
