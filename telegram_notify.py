import requests
from config import TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID

def notify(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: print(text); return
    try: requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',json={'chat_id':TELEGRAM_CHAT_ID,'text':text[:4096]},timeout=20).raise_for_status()
    except Exception as e: print('Telegram:',e)
