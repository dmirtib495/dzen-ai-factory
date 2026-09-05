# Cloud deployment: GitHub Actions + Cloudflare D1/Worker

## Единственный production Worker
Источник правды для Worker находится **в корне репозитория**:
- `index.ts` — Telegram webhook, D1, `/health`, запуск GitHub Actions через `WORKFLOW_TRIGGER_TOKEN`;
- `wrangler.jsonc` — production-конфигурация Wrangler и D1 binding `DB`.

`cloud/src/index.ts` был устаревшей заглушкой и удалён. Не создавайте вторую реализацию Worker в `cloud/`.

## Обязательные GitHub Actions Secrets
- `OPENROUTER_API_KEY`
- `YANDEX_API_KEY`
- `YANDEX_FOLDER_ID`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_D1_DATABASE_ID`

`YANDEX_API_KEY` и `YANDEX_FOLDER_ID` обязательны: YandexGPT — обязательный редакционный этап. `config.validate()` останавливает workflow до первого запроса к OpenRouter, если они отсутствуют.

## Worker secrets
Worker должен иметь:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `CONTROL_SECRET`
- `WORKFLOW_TRIGGER_TOKEN`

`WORKFLOW_TRIGGER_TOKEN` — fine-grained GitHub PAT с правами **Actions: Read and write** на `dmirtib495/dzen-ai-factory`. Его можно установить workflow `Set Cloudflare Worker Secrets` или командой `npx wrangler secret put WORKFLOW_TRIGGER_TOKEN --config wrangler.jsonc`.

## D1 и деплой
1. D1 database: `dzen-auto`.
2. Применить `cloud/schema.sql` к D1.
3. Проверить binding `DB` в корневом `wrangler.jsonc`.
4. Деплоить из **корня**: `npx wrangler deploy --config wrangler.jsonc`.
5. Проверить `https://dzen-auto-control.c4dftyhvv2.workers.dev/health`.
6. Один раз настроить Telegram webhook через `POST /set-webhook` с `x-control-secret`.
7. Кнопка «🚗 Создать статью сейчас» должна делать GitHub `workflow_dispatch` для `.github/workflows/dzen-cloud.yml`.

## Расписание
Workflow `.github/workflows/dzen-cloud.yml` запускается:
- 03:00 UTC = 06:00 Europe/Moscow
- 09:00 UTC = 12:00 Europe/Moscow
- 15:00 UTC = 18:00 Europe/Moscow

В каждом scheduled run установлено `ARTICLES_PER_DAY=1`, поэтому штатная производительность — **3 статьи в сутки**, если каждая проходит AI-цепочку и quality gate.
