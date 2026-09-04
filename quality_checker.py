import re
from config import MIN_ARTICLE_WORDS, MAX_ARTICLE_WORDS

def check_article(data):
    p=[]; text=data.get('article_markdown','')
    words=len(re.findall(r'\b\w+\b',text,flags=re.U))
    if words<MIN_ARTICLE_WORDS: p.append(f'Мало слов: {words}')
    if words>MAX_ARTICLE_WORDS+250: p.append(f'Слишком много слов: {words}')
    if len(data.get('headline',''))<25:p.append('Слабый/короткий заголовок')
    if not data.get('fact_check'):p.append('Нет списка проверки фактов')
    if not data.get('image_prompt'):p.append('Нет промпта изображения')
    if re.search(r'\b(100%|гарантированно|точно лучший|самый лучший|никогда|всегда)',text,re.I):p.append('Есть абсолютные утверждения')
    if len(re.findall(r'^#{2,3}\s+',text,re.M))<4:p.append('Мало подзаголовков')
    return {'ok':not p,'problems':p,'words':words}
