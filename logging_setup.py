import logging
from logging.handlers import RotatingFileHandler
from config import LOG_DIR

def setup_logging():
    logger=logging.getLogger()
    if logger.handlers: return logger
    logger.setLevel(logging.INFO)
    fmt=logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
    fh=RotatingFileHandler(LOG_DIR/'factory.log',maxBytes=1_000_000,backupCount=5,encoding='utf-8')
    fh.setFormatter(fmt); logger.addHandler(fh)
    sh=logging.StreamHandler(); sh.setFormatter(fmt); logger.addHandler(sh)
    return logger
