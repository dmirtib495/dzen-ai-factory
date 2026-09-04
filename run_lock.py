from pathlib import Path
from config import LOCK_PATH

class RunLock:
    def __enter__(self):
        try:
            self.fd = open(LOCK_PATH, 'x', encoding='utf-8')
            self.fd.write(str(__import__('os').getpid())); self.fd.flush(); return self
        except FileExistsError:
            raise RuntimeError('Фабрика уже выполняется (lock активен).')
    def __exit__(self, exc_type, exc, tb):
        try: self.fd.close()
        finally:
            Path(LOCK_PATH).unlink(missing_ok=True)
