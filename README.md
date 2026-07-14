# ЖКонстракт Backend

Backend-сервис для маршрутизации и обработки заявок жителей между ЖК,
ТСЖ и независимыми поставщиками услуг.

## Локальный запуск

Требования:

- Docker Desktop;
- WSL 2 для запуска Linux-контейнеров в Windows.

Создайте локальный файл настроек:

```powershell
Copy-Item .env.example .env
```

Значения из `.env.example` предназначены только для локальной разработки.
Перед использованием в другом окружении замените секреты и пароли.

Соберите и запустите PostgreSQL и Django:

```powershell
docker compose up -d --build
```

Примените миграции:

```powershell
docker compose exec backend python manage.py migrate
```

Backend будет доступен по адресу <http://localhost:8000/>, Django Admin —
по адресу <http://localhost:8000/admin/>.

## Полезные команды

```powershell
# Состояние контейнеров
docker compose ps

# Логи backend
docker compose logs -f backend

# Проверка Django
docker compose exec backend python manage.py check

# Тесты
docker compose exec backend python manage.py test

# Остановка без удаления данных PostgreSQL
docker compose down
```

Данные PostgreSQL хранятся в именованном Docker-томе `postgres_data`.
Команда `docker compose down -v` удаляет этот том вместе с локальной базой.
