# Cloud deployment: GitHub Actions + Cloudflare D1/Worker

Эта папка добавляет облачный контур к Python-фабрике.

## Роли
- GitHub Actions: запускает Python 3 раза в день и вручную.
- Cloudflare D1: постоянное хранилище состояния/статистики.
- Cloudflare Worker: Telegram webhook и панель управления 24/7.
- OpenRouter: генерация текста.
- R2 подключается отдельно при необходимости хранения обложек.

## Важно
Секреты не должны попадать в git. В GitHub Secrets используйте:
`OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_D1_DATABASE_ID`.

Для D1 API Cloudflare официально поддерживает POST `/accounts/{account_id}/d1/database/{database_id}/query` с API Token и SQL-параметрами.

## Первичная настройка
1. Создать аккаунт Cloudflare.
2. Создать D1 database `dzen-auto`.
3. Выполнить `schema.sql` через Wrangler/Dashboard.
4. Скопировать `wrangler.toml.example` в `wrangler.toml` и вставить database_id.
5. Задать Worker secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CONTROL_SECRET`.
6. Деплоить Worker из `cloud/`.
7. Один раз вызвать POST `/set-webhook` с заголовком `x-control-secret`.
8. Создать GitHub Secrets из списка выше.
9. Положить проект в GitHub repository. Для полностью бесплатного Actions используйте public repository.
10. В Actions запустить `Dzen AI Factory — Cloud` вручную для первого теста.

## Расписание
Workflow использует UTC:
- 03:00 UTC = 06:00 Europe/Moscow
- 09:00 UTC = 12:00 Europe/Moscow
- 15:00 UTC = 18:00 Europe/Moscow

GitHub отмечает, что scheduled workflows могут запускаться с задержкой. Не привязывайте бизнес-логику к точной секунде.
