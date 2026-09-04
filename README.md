# Dzen AI Factory v1.1 Cloud — «Авто без переплаты»

Облачная версия без VPS: **GitHub Actions + Cloudflare D1 + Cloudflare Worker + OpenRouter**.

## Что делает
- 3 запуска в день: 06:00 / 12:00 / 18:00 Europe/Moscow.
- В каждом scheduled job создаётся 1 статья, итого 3 статьи/сутки.
- OpenRouter `openrouter/free`.
- Дневной лимит фабрики 50 AI-запросов UTC.
- D1 хранит постоянные статьи, статистику и лимит.
- Worker обслуживает Telegram webhook 24/7.
- Python-фабрика сохраняет готовые материалы в outbox.
- GitHub Actions сохраняет результат запуска как artifact.
- Публикация в Дзен намеренно остаётся отдельным официальным шагом: скрытые/неподтверждённые endpoint'ы не используются.

## Быстрый старт
1. Создай GitHub repository. Для бесплатного Actions используй **public repository**.
2. Загрузи проект целиком.
3. В Cloudflare создай D1 `dzen-auto`.
4. Создай Worker из `cloud/`, привяжи D1 и secrets.
5. В GitHub → Settings → Secrets and variables → Actions добавь:
   - OPENROUTER_API_KEY
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
   - CLOUDFLARE_API_TOKEN
   - CLOUDFLARE_ACCOUNT_ID
   - CLOUDFLARE_D1_DATABASE_ID
6. Запусти workflow вручную для теста.

Подробная инструкция: `cloud/README.md`.
