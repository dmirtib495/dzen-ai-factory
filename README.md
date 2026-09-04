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


