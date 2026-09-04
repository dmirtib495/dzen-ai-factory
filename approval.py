from pathlib import Path
import json
from config import OUTBOX_DIR, APPROVED_DIR, REJECTED_DIR
OUTBOX=OUTBOX_DIR; APPROVED=APPROVED_DIR; REJECTED=REJECTED_DIR

def list_pending(): return sorted(OUTBOX.glob('*.json'))
def approve(manifest_path):
    src=Path(manifest_path)
    if not src.exists(): raise FileNotFoundError(src)
    data=json.loads(src.read_text(encoding='utf-8')); data['status']='approved'
    dst=APPROVED/src.name; dst.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); src.unlink(); return dst

def reject(manifest_path):
    src=Path(manifest_path)
    if not src.exists(): raise FileNotFoundError(src)
    data=json.loads(src.read_text(encoding='utf-8')); data['status']='rejected'
    dst=REJECTED/src.name; dst.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); src.unlink(); return dst
