# AI-чат обращений

Готовая MVP-интеграция находится в приложении `backend/ai_assistant`.

## Быстрый запуск на ноутбуке

Требования:

- Windows;
- Docker Desktop;
- включённый WSL 2 backend в Docker Desktop.

Откройте PowerShell в корне проекта и выполните:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start-demo.ps1
```

После завершения откройте:

- кабинет жителя: <http://localhost:8000/app/login/>
- AI-чат: <http://localhost:8000/app/ai-chat/>
- Django Admin: <http://localhost:8000/admin/>

Демо-доступы:

- житель: `demo-resident` / `DemoUser2026!`
- админ: `admin` / `Admin2026!`

## Как проверить чат

Войдите жителем и откройте AI-чат. Пример сообщения:

```text
В третьем подъезде прорвало трубу, вода течет на лестницу.
```

Чат должен выделить краткую тему, категорию, место и срочность. После кнопки
`Отправить заявку в ТСЖ` появится обычная заявка в разделе обращений.

## OpenAI API

Для демо ключ не обязателен: включён fallback по правилам, чтобы чат работал
сразу. Для настоящего AI-анализа добавьте в `.env`:

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
AI_ASSISTANT_ALLOW_FALLBACK=true
```

Ключ хранится только на backend и не попадает во frontend.

## Ручные команды без скрипта

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_demo_data `
  --admin-password Admin2026! `
  --demo-password DemoUser2026!
```

Остановить проект:

```powershell
docker compose down
```
