from approval import list_pending
from config import APPROVED_DIR, REJECTED_DIR
from quota import status as quota_status

def status():
    q=quota_status()
    return {'pending':len(list_pending()),'approved':len(list(APPROVED_DIR.glob('*.json'))),'rejected':len(list(REJECTED_DIR.glob('*.json'))),'ai':q}
