# Карта сервисов и API

Документ фиксирует актуальные сервисы, публичные endpoint'ы и потоки данных между ними.

## Сервисы

- `frontend` (`5173`) - пользовательский интерфейс студента.
- `core` (`8000`) - авторизация, задания, прием сдачи, прокси к `wiki`.
- `wiki` (`8001`) - материалы лабораторных и поиск по ним.
- `postgres` (`5432`) - пользователи, задания, сдачи.
- `mongo` (`27017`) - материалы wiki.
- `meilisearch` (`7700`) - внутренний поисковый движок `wiki`.

## Frontend маршруты

- `GET /login`
- `GET /assignments`
- `GET /assignments/:assignmentId`
- `GET /wiki`
- `GET /wiki/:slug`

Frontend обращается к backend через `VITE_API_BASE_URL`, по умолчанию `http://localhost:8000`.

## Core API

Базовый URL: `http://localhost:8000`

### Без авторизации

- `GET /health`
  - ответ: `{ "status": "ok" }`

- `POST /auth/login`
  - body:
    - `email`
    - `password`
  - ответ:
    - `access_token`
    - `refresh_token`
    - `token_type`

- `POST /auth/refresh`
  - body:
    - `refresh_token`
  - ответ:
    - новый `access_token`
    - новый `refresh_token`
    - `token_type`

- `POST /auth/logout`
  - body:
    - `refresh_token`
  - ответ:
    - `status: "logged_out"`

### С авторизацией

Все endpoint'ы ниже требуют `Authorization: Bearer <access_token>`, кроме `/wiki/assets/...`.

- `GET /assignments`
  - список доступных заданий студента
  - статус задания: `open | deadline_passed | submitted | submitted_late | closed`

- `GET /assignments/{assignment_id}`
  - детальная карточка задания
  - основные поля:
    - `title`
    - `description`
    - `deadline`
    - `wiki_url`
    - `requires_report_docx`
    - `code_submission_mode`

- `GET /assignments/{assignment_id}/submission-status`
  - возвращает текущее состояние сдачи:
    - `submitted`
    - `submitted_at`
    - `submission_id`
    - `status`
    - `can_submit`
    - `report_file_name`
    - `code_link`
    - `code_file_names`
    - `report_submitted`
    - `code_submitted`
    - `submitted_late`

- `POST /assignments/{assignment_id}/submit`
  - `multipart/form-data`
  - поля:
    - `report_file` - один `.docx`, необязателен
    - `code_files[]` - 0..N файлов кода, необязательны
    - `submission_meta` - JSON-строка
  - `submission_meta`:
    - `assignment_id: int`
    - `comment: string`
    - `submitted_at: ISO datetime`
    - `code_mode: "file" | "link"`
    - `code_link: string`
    - `delete_report: boolean`
    - `delete_code: boolean`
  - поддерживаемые сценарии:
    - первая сдача отчета и кода
    - сдача только отчета
    - сдача только кода
    - обновление только отчета
    - обновление только кода
    - удаление только отчета
    - удаление только кода
  - ограничения:
    - нельзя удалить отчет и код одновременно, если после этого не остается ни одной части
    - для ссылочного кода допустимы только разрешенные хосты

- `GET /wiki/labs`
  - прокси к `wiki /labs`

- `GET /wiki/labs/{slug}`
  - прокси к `wiki /labs/{slug}`

- `GET /wiki/search`
  - параметры:
    - `q`
    - `tag`
    - `kind`
    - `lab_slug`
    - `limit`
  - прокси к `wiki /search`

- `GET /wiki/assets/{asset_path}`
  - прокси к статическим ассетам wiki
  - Bearer token не требуется

## Wiki API

Базовый URL: `http://localhost:8001`

- `GET /health`
- `GET /labs`
- `GET /labs/{slug}`
- `GET /search`
- `GET /assets/{path}`

`wiki` не должен использоваться клиентом напрямую. Внешние клиенты ходят через `core`.

## Уведомления и события

### Callback из `core`

Если задан `CALLBACK_URL`, `core` отправляет HTTP callback при создании или обновлении сдачи.

Типы событий:

- `submission.created`
- `submission.updated`

Payload содержит:

- `event_type`
- `submission_id`
- `student_id`
- `assignment_id`
- `files[]`
- `created_at`
- `message`
- `late_submission`

Если внешний сервис недоступен, сдача не теряется: данные уже сохранены в `postgres` и на диске, а ошибка уходит в лог.

## Потоки данных

### Вход

1. Frontend вызывает `POST /auth/login`.
2. `core` проверяет пользователя в `postgres`.
3. `core` выдает JWT токены.
4. Frontend использует `access_token` в `Authorization`.

### Выход

1. Frontend вызывает `POST /auth/logout`.
2. `core` добавляет refresh token в denylist.
3. Frontend очищает локальную сессию.

### Просмотр заданий

1. Frontend -> `GET /assignments`
2. `core` читает `assignments` и `submissions` из `postgres`
3. `core` рассчитывает итоговый статус для студента

### Просмотр wiki

1. Frontend -> `GET /wiki/labs` или `GET /wiki/labs/{slug}` через `core`
2. `core` проксирует запрос в `wiki`
3. `wiki` читает данные из `mongo`
4. `wiki` при необходимости использует `meilisearch` для поиска

### Сдача работы

1. Frontend -> `POST /assignments/{id}/submit`
2. `core` валидирует дедлайн, формат файлов и `submission_meta`
3. `core` обновляет запись сдачи в `postgres`
4. `core` сохраняет файлы в `data/submissions`
5. `core` обновляет `submission.json`
6. при наличии `CALLBACK_URL` отправляется callback

## Где физически лежат данные

- данные `postgres`: volume `postgres_data`
- данные `mongo`: volume `mongo_data`
- файлы сдач: bind mount `data/submissions:/data/submissions`

Текущая структура файлов сдачи:

```text
data/submissions/
  student-1/
    assignment-1-lr01-introduction-and-tooling/
      report/
      code/
      submission.json
```

## Что важно помнить

- `submission_id` - это ID записи сдачи, а не номер лабораторной.
- `assignment_id` - это ID задания в `core`.
- `wiki_slug` - это строковый идентификатор ЛР в `wiki`.
- `core` остается единой точкой входа для web и mobile клиентов.
