# Хранение данных в `core` и `wiki`

Документ описывает, где и в каком виде сейчас хранятся данные системы.

## `core`: PostgreSQL

Основные модели находятся в [models.py](/d:/data/projects/CourseProjects/third%20course%20project/core/src/infrastructure/db/models.py).

### `students`

Поля:

- `id`
- `email`
- `full_name`
- `password_hash`

Назначение:

- учетные записи студентов для авторизации.

### `assignments`

Поля:

- `id`
- `title`
- `description`
- `deadline`
- `status`
- `wiki_slug`

Назначение:

- список лабораторных, доступных студенту;
- связь с материалами `wiki` через `wiki_slug`.

### `submissions`

Поля:

- `id`
- `assignment_id`
- `student_id`
- `comment`
- `submitted_at`
- `status`

Назначение:

- запись о текущей сдаче задания студентом;
- при повторной отправке та же запись обновляется.

### `submission_files`

Поля:

- `id`
- `submission_id`
- `file_name`
- `content_type`
- `size`
- `storage_path`

Назначение:

- метаданные файлов отчета и файлов кода;
- роль файла определяется серверной логикой по расширению и MIME type.

### `submission_code_references`

Поля:

- `id`
- `submission_id`
- `url`

Назначение:

- хранение ссылки на код, если студент сдает код ссылкой, а не файлами.

### `revoked_refresh_tokens`

Поля:

- `id`
- `jti`
- `student_id`
- `expires_at`

Назначение:

- denylist refresh token после logout.

## `core`: файловая система

Кроме `postgres`, сервис `core` хранит файлы сдач на диске.

Базовый путь:

- локально: `data/submissions`
- в контейнере: `/data/submissions`

Текущая структура:

```text
data/submissions/
  student-<student_id>/
    assignment-<assignment_id>-<wiki_slug>/
      report/
        <uuid>_<original_report_name>.docx
      code/
        <uuid>_<original_code_file>
      submission.json
```

### Что лежит в `submission.json`

Файл содержит удобные для отладки и интеграции метаданные:

- `student_id`
- `student_email`
- `assignment_id`
- `assignment_title`
- `wiki_slug`
- `submission_id`
- `submitted_at`
- `report_file_name`
- `code_file_names`
- `code_link`

Зачем это нужно:

- удобно смотреть руками содержимое папки без запроса в БД;
- проще интегрироваться с внешними сервисами;
- проще демонстрировать работу системы на защите.

## `wiki`: MongoDB

Подключение настраивается в `wiki/src/core/config.py`.

По умолчанию:

- база: `lms_wiki`
- коллекция: `labs`

Один документ Mongo = одна лабораторная работа.

### Структура документа `labs`

Поля верхнего уровня:

- `lab_id`
- `slug`
- `title`
- `source_file`
- `tags`
- `sections`
- `assets`
- `stats`
- `search_text`
- `updated_at`

### `sections[]`

Каждая секция содержит:

- `id`
- `title`
- `kind`
- `order`
- `content_md`
- `tags`
- `assets`

### `assets[]`

Каждый ассет содержит:

- `id`
- `url`
- `type`
- `caption`

## `wiki`: curated-слой на диске

Перед загрузкой в Mongo материалы лежат в файловой структуре:

```text
wiki/materials/curated/<lab-slug>/
  meta.yaml
  sections/
    01-...
    02-...
  assets/
    img-...
```

`curated` сейчас является финальным слоем материалов:

- если папка уже существует, `wiki` использует ее как источник истины;
- пайплайн нужен для первичной генерации или пересборки отсутствующих ЛР.

## `wiki`: Meilisearch

`Meilisearch` встроен как внутренний поисковый движок `wiki`.

Важно:

- это отдельный контейнер;
- это не публичный API для клиента;
- web и mobile клиенты все равно ходят только в `core`.

### Индекс

По умолчанию используется индекс:

- `wiki_sections`

Один документ индекса = одна секция ЛР.

Поля документа индекса:

- `id`
- `lab_id`
- `lab_slug`
- `lab_title`
- `section_id`
- `section_title`
- `kind`
- `order`
- `tags`
- `content_plain`

## Как связаны `core`, `wiki`, `mongo`, `meilisearch`

1. В `assignments.wiki_slug` хранится идентификатор ЛР.
2. `core` по `wiki_slug` проксирует запросы в `wiki`.
3. `wiki` берет материалы из `mongo`.
4. `wiki` ищет по секциям через `meilisearch`.
5. Если `meilisearch` недоступен, `wiki` использует fallback-поиск по MongoDB и Python-эвристике.

Итоговая ответственность хранилищ:

- `postgres` - пользователи, задания, сдачи;
- файловая система `core` - загруженные файлы студентов;
- `mongo` - материалы wiki как основной источник данных;
- `meilisearch` - поисковый индекс по секциям wiki.
