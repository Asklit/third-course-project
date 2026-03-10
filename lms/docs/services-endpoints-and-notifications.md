# Карта сервисов и API (LMS)

Документ описывает, какие эндпоинты есть в каждой части системы, какие события/уведомления отправляются и как ходят данные между сервисами.

## 1) Сервисы и роли

- `frontend` (порт `5173`): UI для студента.
- `core` (порт `8000`): основная бизнес-логика, авторизация, задания, сдача работ.
- `wiki` (порт `8001`): выдача материалов лабораторных.
- `postgres` (порт `5432`): хранение пользователей, заданий, сдач, метаданных файлов.
- `mongo` (порт `27017`): хранение wiki-материалов.

См. compose: `lms/docker-compose.yml`.

## 2) Frontend маршруты

Браузерные маршруты (React Router):

- `GET /login` — страница входа.
- `GET /assignments` — список работ (требует авторизацию).
- `GET /assignments/:assignmentId` — карточка конкретной работы (требует авторизацию).
- `*` -> редирект на `/assignments`.

Frontend API base URL:

- `VITE_API_BASE_URL` (по умолчанию `http://localhost:8000`).

## 3) Core API (`http://localhost:8000`)

### Без авторизации

- `GET /health`
  - Ответ: `{ "status": "ok" }`

- `POST /auth/login`
  - Body JSON:
    - `email: string`
    - `password: string`
  - Ответ:
    - `access_token: string`
    - `refresh_token: string`
    - `token_type: "bearer"`

- `POST /auth/refresh`
  - Body JSON:
    - `refresh_token: string`
  - Ответ: новый `access_token` + `refresh_token`.

### С авторизацией (`Authorization: Bearer <access_token>`)

- `GET /assignments`
  - Возвращает видимые задания для студента.
  - `status` может быть: `open | deadline_passed | submitted | submitted_late | closed`.

- `GET /assignments/{assignment_id}`
  - Детали задания: `title`, `description`, `deadline`, `wiki_url`, требования к сдаче.

- `GET /assignments/{assignment_id}/submission-status`
  - Статус сдачи текущим студентом:
    - `submitted`, `submitted_at`, `submission_id`, `can_submit`, `code_link`, `submitted_late`.

- `POST /assignments/{assignment_id}/submit`
  - `multipart/form-data`:
    - `report_file` (один файл, .docx)
    - `code_files[]` (0..N файлов, если режим `file`)
    - `submission_meta` (JSON-строка)
  - Структура `submission_meta`:
    - `assignment_id: int`
    - `comment: string`
    - `submitted_at: ISO datetime`
    - `code_mode: "file" | "link"`
    - `code_link: string` (если `code_mode=link`)
  - Ответ:
    - `status: "accepted"`
    - `submission_id: int` (это ID записи сдачи, не номер лабораторной)

- `GET /wiki/labs`
  - Проксирует запрос в Wiki сервис `/labs`.

- `GET /wiki/labs/{slug}`
  - Проксирует запрос в Wiki сервис `/labs/{slug}`.

## 4) Wiki API (`http://localhost:8001`)

- `GET /health`
- `GET /labs` — список материалов (`slug`, `title`)
- `GET /labs/{slug}` — материал лабораторной (`slug`, `title`, `content_md`, `prerequisites`)

## 5) Уведомления и события

### Callback из `core` во внешний сервис

`core` может отправлять HTTP callback при сдаче/обновлении работы, если задан `CALLBACK_URL`.

- Триггер:
  - новая сдача -> `event_type = submission.created`
  - обновление сдачи -> `event_type = submission.updated`
- Способ отправки:
  - `POST {CALLBACK_URL}`
  - `Content-Type: application/json`
- Payload:
  - `event_type`
  - `submission_id`
  - `student_id`
  - `assignment_id`
  - `files[]` (имя/тип/размер/путь/роль)
  - `created_at`
  - `message`
  - `late_submission` (вычисляется на backend)

Если `CALLBACK_URL` пустой, callback пропускается.

Других нотификаций (email/ws/telegram) в текущей реализации нет.

## 6) Потоки данных

### Вход пользователя

1. Frontend -> `POST /auth/login` (core)
2. Core проверяет пользователя в Postgres.
3. Core возвращает JWT токены.
4. Frontend сохраняет токен и использует его в `Authorization`.

### Просмотр заданий

1. Frontend -> `GET /assignments` (core)
2. Core читает задания/сдачи из Postgres, рассчитывает статус.
3. Frontend показывает список.

### Просмотр материалов

1. Frontend -> `GET /wiki/labs/{slug}` через core.
2. Core -> Wiki `/labs/{slug}`.
3. Wiki читает Mongo и возвращает markdown.
4. Core отдает ответ frontend.

### Сдача работы

1. Frontend -> `POST /assignments/{id}/submit` (multipart).
2. Core валидирует:
   - доступность задания,
   - формат отчета,
   - режим сдачи кода (`file`/`link`),
   - допустимый хост для ссылки.
3. Core сохраняет:
   - метаданные в Postgres,
   - файлы в `SUBMISSIONS_DIR`.
4. При наличии `CALLBACK_URL` отправляет callback.

## 7) Где физически хранятся данные

- Postgres данные: volume `postgres_data`.
- Mongo данные: volume `mongo_data`.
- Файлы сдач (`core`): bind-mount
  - host: `data/submissions`
  - container: `/data/submissions`

Структура файлов сдачи:

- `data/submissions/{student_id}/{submission_id}/{uuid}_{original_filename}`

## 8) Полезные замечания

- `submission_id` — это ID попытки сдачи, не номер лабораторной.
- В ответах сервис добавляет `X-Trace-Id` для трассировки запросов.
- Ошибки в `core`/`wiki` возвращаются как HTTP-коды с `detail`.
