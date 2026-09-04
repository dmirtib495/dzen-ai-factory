import json,re,time,logging
from openai import OpenAI
from config import OPENROUTER_API_KEY,OPENROUTER_MODEL,CHANNEL_NAME,MIN_ARTICLE_WORDS,MAX_ARTICLE_WORDS,OPENROUTER_DAILY_LIMIT
from quota import reserve

log=logging.getLogger(__name__)
SYSTEM=f'''Ты главный редактор автомобильного канала «{CHANNEL_NAME}». Пиши оригинальные полезные материалы на русском.
Не копируй источники и не выдумывай факты, цены, характеристики, законы, цитаты или результаты тестов.
Если точное значение не подтверждено входными данными, пометь его как «нужно проверить».
Не используй абсолютные обещания и кликбейт. Даже новость превращай в практический разбор для владельца или покупателя.'''

def _extract(s):
    s=s.strip()
    if s.startswith('```'): s=re.sub(r'^```(?:json)?\s*|\s*```$','',s,flags=re.I|re.S)
    try:return json.loads(s)
    except Exception:
        m=re.search(r'\{.*\}',s,re.S); return json.loads(m.group(0)) if m else None

def generate_article(topic):
    if not OPENROUTER_API_KEY: raise RuntimeError('OPENROUTER_API_KEY не задан')
    client=OpenAI(api_key=OPENROUTER_API_KEY,base_url='https://openrouter.ai/api/v1',timeout=120,max_retries=0)
    prompt=f'''Источник темы: {topic.get('source','')}
Заголовок исходной темы: {topic['title']}
Ссылка: {topic.get('link','')}
Описание: {topic.get('summary','')}

Сделай самостоятельный материал {MIN_ARTICLE_WORDS}–{MAX_ARTICLE_WORDS} слов. Нужны лид, 5–8 подзаголовков, практические пункты и честный вывод.
Сразу предложи 5 разных заголовков, затем выбери смысловую категорию только из: Что купить; Стоит ли брать; Экономия; Сравнения; Авто-технологии.
Верни ТОЛЬКО JSON: headline, headlines (array из 5 строк), category, article_markdown, fact_check (array), image_prompt, source_urls (array), commercial_intent (0..10).'''
    last=None
    for attempt in range(3):
        try:
            if not reserve(): raise RuntimeError(f'Дневной лимит OpenRouter исчерпан ({OPENROUTER_DAILY_LIMIT} запросов)')
            r=client.chat.completions.create(model=OPENROUTER_MODEL,messages=[{'role':'system','content':SYSTEM},{'role':'user','content':prompt}],temperature=0.55)
            data=_extract(r.choices[0].message.content or '')
            if not data: raise ValueError('AI вернул невалидный JSON')
            data.setdefault('headlines',[data.get('headline','')]); data.setdefault('fact_check',[]); data.setdefault('source_urls',[]); data.setdefault('category','Стоит ли брать'); data.setdefault('commercial_intent',5)
            return data
        except Exception as e:
            last=e; log.warning('OpenRouter attempt %s failed: %s',attempt+1,e)
            if '429' not in str(e).lower() or attempt==2: break
            time.sleep(2**attempt*3)
    raise RuntimeError(f'OpenRouter: {last}')
