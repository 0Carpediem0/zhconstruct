# ЖКонстракт (zhconstruct)

**Командный учебный проект — платформа для управления заявками жителей, ТСЖ и подрядных организаций.**

Проект объединяет обработку обращений жителей, маршрутизацию заявок и взаимодействие с подключёнными поставщиками услуг. Разработка ведётся в отдельных ветках: **в `main` сейчас находится документация, а не собранная версия приложения**.

## Возможности проекта

По состоянию кода в ветке [`client-web-skeleton+ai`](https://github.com/0Carpediem0/zhconstruct/tree/client-web-skeleton%2Bai):

- Кабинет жителя: обращения в ТСЖ, новости дома, профиль, начисления ЖКХ и витрина услуг.
- Создание заявок и маршрутизация между диспетчером ТСЖ и подключёнными подрядчиками по настроенным правилам.
- Настройка услуг подрядчиков и оформление заказов через кабинет жителя.
- Служебные роли и управление доступом.
- Экспериментальный AI-чат для оформления обращений: выделение темы, категории, места и срочности. Предусмотрены подключение API модели и резервный разбор по правилам.

> Это описание функциональности **ветки разработки**, а не утверждение о готовом публичном релизе или развёрнутом сервисе.

## Технологии

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-092E20?style=flat-square&logo=django&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black)
![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=flat-square&logo=html5&logoColor=white)
![CSS3](https://img.shields.io/badge/CSS3-1572B6?style=flat-square&logo=css&logoColor=white)

## Ветки проекта

| Ветка | Содержимое |
| --- | --- |
| [`main`](https://github.com/0Carpediem0/zhconstruct/tree/main) | Описание проекта; пока без исходного кода приложения |
| [`backend1`](https://github.com/0Carpediem0/zhconstruct/tree/backend1) | Django backend, модели заявок и маршрутизации, PostgreSQL, Docker Compose |
| [`frontendforkirillshoshev`](https://github.com/0Carpediem0/zhconstruct/tree/frontendforkirillshoshev) | Отдельная ветка веб-интерфейса |
| [`client-web-skeleton`](https://github.com/0Carpediem0/zhconstruct/tree/client-web-skeleton) | Совместная структура frontend и backend, кабинет жителя |
| [`client-web-skeleton+ai`](https://github.com/0Carpediem0/zhconstruct/tree/client-web-skeleton%2Bai) | Расширение объединённой версии AI-чатом и демозапуском |

**Для изучения наиболее полной версии см. [`client-web-skeleton+ai`](https://github.com/0Carpediem0/zhconstruct/tree/client-web-skeleton%2Bai).** Изменения из веток пока не объединены в `main`.

## Локальный запуск версии разработки

Инструкции относятся к ветке `client-web-skeleton+ai`. Необходимы Docker Desktop и (для Windows) WSL 2.

```bash
git clone -b "client-web-skeleton+ai" https://github.com/0Carpediem0/zhconstruct.git
cd zhconstruct
```

В PowerShell создайте файл окружения:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose exec backend python manage.py migrate
```

После запуска: [кабинет жителя](http://localhost:8000/app/), [Django Admin](http://localhost:8000/admin/).

Для демонстрационных данных и AI-чата смотрите документацию в ветке разработки: [README](https://github.com/0Carpediem0/zhconstruct/blob/client-web-skeleton%2Bai/README.md) и [README_AI_CHAT](https://github.com/0Carpediem0/zhconstruct/blob/client-web-skeleton%2Bai/README_AI_CHAT.md).

> Не используйте демонстрационные пароли и настройки окружения в публичном развёртывании. Для использования внешней AI-модели требуется собственный API-ключ; ключ нельзя коммитить в репозиторий.

## Командная разработка

Проект ведётся совместно. Функции и компоненты распределены между участниками; принадлежность репозитория не означает единоличного авторства кода. История изменений и ветки позволяют посмотреть ход работы.

Перед полноценным релизом планируется согласовать командные изменения, проверить запуск и тесты интегрированной версии, а затем перенести проверенный код в `main`.

---

<details>
<summary><strong>English summary</strong></summary>

**Zhconstruct** is a collaborative educational project for handling residents' requests and coordinating housing-management organizations with service providers.

The development branches contain a Django/PostgreSQL backend, a resident web portal, service request routing, and an experimental AI-assisted request form.

The `main` branch currently contains project documentation only. For the more complete development version and setup instructions, see [`client-web-skeleton+ai`](https://github.com/0Carpediem0/zhconstruct/tree/client-web-skeleton%2Bai).

This repository represents **team development**, not a solo project.

</details>
