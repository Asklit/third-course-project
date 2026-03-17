# Wiki API

Документ описывает, как клиент получает материалы лабораторных через `core`.

## Базовая схема

1. Клиент логинится в `core` и получает `access_token`.
2. Клиент запрашивает список лабораторных через `GET /wiki/labs`.
3. Клиент выбирает `slug` нужной ЛР.
4. Клиент запрашивает полную ЛР через `GET /wiki/labs/{slug}`.
5. Клиент рендерит `sections[].content_md` как markdown.
6. Если в markdown есть ссылки на картинки, клиент загружает их через `GET /wiki/assets/{asset_path}`.

## Авторизация

Требует `Authorization: Bearer <access_token>`:

- `GET /wiki/labs`
- `GET /wiki/labs/{slug}`
- `GET /wiki/search`

Не требует Bearer token:

- `GET /wiki/assets/{asset_path}`

## Endpoint'ы

### `GET /wiki/labs`

Возвращает список доступных материалов.

Пример ответа:

```json
[
  {
    "lab_id": 1,
    "slug": "lr01-introduction-and-tooling",
    "title": "Лабораторная работа №1",
    "tags": ["console", "csharp", "math"],
    "sections_count": 8
  }
]
```

Что это значит:

- `slug` нужен, чтобы открыть конкретную ЛР;
- `tags` можно использовать в фильтрах;
- `sections_count` показывает количество секций внутри работы.

### `GET /wiki/labs/{slug}`

Возвращает полную ЛР со всеми секциями и списком ассетов.

Пример запроса:

```http
GET /wiki/labs/lr01-introduction-and-tooling
Authorization: Bearer <access_token>
```

Пример ответа:

```json
{
  "lab_id": 1,
  "slug": "lr01-introduction-and-tooling",
  "title": "Лабораторная работа №1",
  "sections": [
    {
      "id": "цель-задания",
      "title": "Цель задания",
      "kind": "goal",
      "order": 1,
      "content_md": "1. Определение типов переменных.\n2. Организация ввода и вывода данных.",
      "tags": ["console", "csharp"],
      "assets": []
    }
  ],
  "assets": [
    {
      "id": "asset-001",
      "url": "/assets/lr01-introduction-and-tooling/assets/img-066.png",
      "type": "image",
      "caption": "Иллюстрация"
    }
  ]
}
```

Что это значит:

- `sections[]` содержит смысловые блоки одной ЛР;
- `content_md` уже готов для рендера как markdown;
- `assets[]` содержит список картинок и других файлов, которые используются внутри секций.

### `GET /wiki/search`

Поиск возвращает не всю лабораторную, а найденные секции и фрагменты текста.

Пример запроса:

```http
GET /wiki/search?q=console&kind=theory&limit=10
Authorization: Bearer <access_token>
```

Пример ответа:

```json
{
  "total": 1,
  "items": [
    {
      "lab_slug": "lr01-introduction-and-tooling",
      "lab_title": "Лабораторная работа №1",
      "section_id": "теоретические-сведения",
      "section_title": "Теоретические сведения",
      "kind": "theory",
      "snippet": "Console.WriteLine используется для вывода...",
      "tags": ["console", "теория"]
    }
  ]
}
```

Что это значит:

- найдено совпадение в секции `Теоретические сведения`;
- `snippet` показывает, где именно найден текст;
- для открытия полного материала нужно перейти на `GET /wiki/labs/{lab_slug}` и прокрутить к `section_id`.

### `GET /wiki/assets/{asset_path}`

Возвращает картинку или другой ассет, который использует markdown.

Пример:

```http
GET /wiki/assets/lr01-introduction-and-tooling/assets/img-066.png
```

Ответ: бинарное содержимое файла с корректным `Content-Type`.

## Как рендерить материалы

Клиенту достаточно уметь:

- markdown;
- таблицы;
- списки;
- fenced code blocks;
- inline code;
- изображения;
- raw HTML теги вроде `<br>`.

Практически это означает:

1. взять `sections[].content_md`;
2. отрендерить markdown;
3. если встретился путь `/assets/...`, преобразовать его в запрос к `GET /wiki/assets/{asset_path}`.

## Что важно для mobile-клиента

- внешний клиент не должен ходить напрямую в `wiki`;
- работать нужно через `core`;
- `slug` используется как стабильный URL-ключ лабораторной;
- `section_id` используется как якорь для перехода к нужной части ЛР;
- картинки не нужно читать вручную с диска, они загружаются обычным HTTP GET.
