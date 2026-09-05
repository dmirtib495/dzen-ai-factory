# Dzen AI Factory v1.2 Cloud — «Авто без переплаты»

Облачная версия без VPS: **GitHub Actions + Cloudflare D1 + Cloudflare Worker + OpenRouter + YandexGPT**.

## Что делает
- 3 запуска в день: 06:00 / 12:00 / 18:00 Europe/Moscow.
- В каждом scheduled job создаётся 1 статья, итого 3 статьи/сутки.
- Черновик: DeepSeek через OpenRouter; обязательная редактура: YandexGPT; финальная редактура/аудит: OpenAI либо OpenRouter fallback.
- Дневной локальный счётчик OpenRouter — телеметрия; фактические ограничения задаёт провайдер.
- D1 хранит статьи, статистику и состояние.
- Единственный production Worker: корневой `index.ts`, конфигурация `wrangler.jsonc`.
- Публикация в Дзен остаётся отдельным официальным шагом: неподтверждённые приватные endpoint'ы не используются.

## Обязательные GitHub Actions Secrets
В GitHub → Settings → Secrets and variables → Actions должны быть созданы:
- `OPENROUTER_API_KEY`
- `YANDEX_API_KEY`
- `YANDEX_FOLDER_ID`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_D1_DATABASE_ID`

Дополнительно:
- `OPENAI_API_KEY` — опционально; без него финальная редактура идёт через OpenRouter.
- `CONTROL_SECRET` и `WORKFLOW_TRIGGER_TOKEN` — нужны Cloudflare Worker. `WORKFLOW_TRIGGER_TOKEN` — fine-grained GitHub PAT с `Actions: Read and write` для этого репозитория.

`YANDEX_API_KEY` и `YANDEX_FOLDER_ID` обязательны. `config.validate()` проверяет их до запуска генерации, поэтому квота OpenRouter не должна тратиться на черновик при отсутствующей конфигурации YandexGPT.

## Быстрый старт
1. Создать D1 `dzen-auto` и применить `cloud/schema.sql`.
2. Проверить `wrangler.jsonc` и задеплоить **корневой** Worker `index.ts`.
3. Задать Worker secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CONTROL_SECRET`, `WORKFLOW_TRIGGER_TOKEN`.
4. Добавить обязательные GitHub Actions Secrets из списка выше.
5. Запустить `Dzen AI Factory - Cloud` (`.github/workflows/dzen-cloud.yml`) через `workflow_dispatch`.

Подробная инструкция: `cloud/README.md`.
