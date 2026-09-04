from datetime import datetime
from shutil import copy2
from config import DB_PATH, BACKUP_DIR

def backup_db():
    if not DB_PATH.exists(): return None
    dst=BACKUP_DIR/f"factory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    copy2(DB_PATH,dst)
    return dst
