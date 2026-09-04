import argparse, logging
from logging_setup import setup_logging
from config import validate, SCHEDULE_HOURS, TIMEZONE
from publication_status import status
from analytics import import_metrics, learn_strategy

setup_logging()
log=logging.getLogger(__name__)
parser=argparse.ArgumentParser(description='Dzen AI Factory v1.0')
parser.add_argument('--once',action='store_true')
parser.add_argument('--status',action='store_true')
parser.add_argument('--import-metrics',metavar='FILE')
parser.add_argument('--strategy',action='store_true')
args=parser.parse_args()

if args.status:
    print(status())
elif args.import_metrics:
    print('Импортировано строк:',import_metrics(args.import_metrics)); learn_strategy()
elif args.strategy:
    print(learn_strategy())
elif args.once:
    errors=validate()
    if errors: raise SystemExit('Конфигурация: '+'; '.join(errors))
    from pipeline import generate_batch
    print('Создано материалов:',generate_batch())
else:
    errors=validate()
    if errors: raise SystemExit('Конфигурация: '+'; '.join(errors))
    from pipeline import generate_batch
    from apscheduler.schedulers.blocking import BlockingScheduler
    scheduler=BlockingScheduler(timezone=TIMEZONE)
    for h in SCHEDULE_HOURS:
        scheduler.add_job(generate_batch,'cron',hour=h,minute=0,id=f'generate_{h}',replace_existing=True,coalesce=True,max_instances=1)
    print(f'Dzen AI Factory v1.0 запущена: {SCHEDULE_HOURS} ({TIMEZONE})')
    scheduler.start()
