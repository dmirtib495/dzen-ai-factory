from title_lab import rank_titles
from quality_checker import check_article
from quota import status

def test_title_lab():
    x=rank_titles(['Купить авто: 7 ошибок перед сделкой','100% лучший автомобиль!!!'],'Что купить')
    assert x[0]['title']=='Купить авто: 7 ошибок перед сделкой'

def test_quality():
    d={'headline':'Нормальный заголовок для статьи об автомобиле','article_markdown':('## Раздел\n\n'+'слово '*200+'\n\n')*5,'fact_check':['проверить цену'],'image_prompt':'car'}
    assert check_article(d)['ok']

def test_quota_shape():
    q=status(); assert q['remaining']>=0 and q['limit']>=q['used']
