from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import textwrap,re,datetime
OUT=Path('data/images'); OUT.mkdir(parents=True,exist_ok=True)

def make_cover(title,category='Авто'):
    safe=re.sub(r'[^\w\-а-яА-Я ]+','',title)[:60].strip().replace(' ','_') or 'article'
    path=OUT/(datetime.datetime.now().strftime('%Y%m%d_%H%M%S_')+safe+'.jpg')
    img=Image.new('RGB',(1600,900),'#171a1f'); d=ImageDraw.Draw(img)
    # Простая бесплатная обложка без внешнего API: не требует ключей и не нарушает авторские права.
    for x in range(0,1600,40): d.rectangle((x,0,x+20,900),fill=(24+x//20%20,28+x//30%18,35+x//40%20))
    try: font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',58); small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',30)
    except: font=small=None
    d.text((90,100),category.upper(),font=small,fill='white')
    lines=textwrap.wrap(title,width=34)
    y=210
    for line in lines[:5]: d.text((90,y),line,font=font,fill='white'); y+=72
    d.rounded_rectangle((90,760,430,825),radius=18,fill=(230,230,230)); d.text((120,778),'АВТО БЕЗ ПЕРЕПЛАТЫ',font=small,fill=(20,20,20))
    img.save(path,quality=90); return path
