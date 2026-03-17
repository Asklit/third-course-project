# Пайплайн Wiki

## Последовательность действий

- Получить конфигурацию ЛР из `LAB_SOURCE_CONFIG` в `wiki/src/application/services/materials_pipeline.py`
- Проверить наличие `wiki/materials/curated/<lab-slug>`
- Если `curated` уже существует, прочитать `meta.yaml` и `sections/*.md`, собрать структуру ЛР из готовых файлов
- Если `curated` отсутствует, открыть исходный `.docx` из `wiki/materials/sources` как zip-архив через стандартный модуль `zipfile`
- Извлечь `word/document.xml`
- Извлечь `word/styles.xml`
- Извлечь `word/numbering.xml`
- Извлечь `word/_rels/document.xml.rels`
- Прочитать `word/media/*`
- Определить стили заголовков по `styles.xml`
- Определить типы списков по `numbering.xml`
- Построить связи `rId -> media target` по `document.xml.rels`
- Пройти по `document.xml` и выделить блоки: абзацы, таблицы, списки, формулы, изображения
- Для каждого абзаца извлечь текстовые фрагменты, OMML-формулы и встроенные изображения
- Для каждой таблицы извлечь строки, ячейки и ссылки на изображения
- Определить структурные заголовки и собрать секции ЛР
- Классифицировать секции по `kind`: `goal`, `theory`, `task`, `variants`, `report`, `qa`, `method`, `content`
- Скопировать изображения в `wiki/materials/curated/<lab-slug>/assets`
- Для `wmf/emf` попытаться конвертировать файл в `png`
- Для `png/jpg/jpeg` выполнить trim лишних полей изображения
- Собрать markdown строк секции: абзацы, списки, таблицы, code block, формулы, изображения
- Выполнить постобработку проблемных секций через `_postprocess_lab_markdown(...)`
- Сохранить итоговые секции в `wiki/materials/curated/<lab-slug>/sections/*.md`
- Сгенерировать `wiki/materials/curated/<lab-slug>/meta.yaml`
- Собрать итоговый объект ЛР для загрузки в MongoDB
- На старте `wiki` вызвать `build_curated_labs()` и upsert документов в MongoDB коллекцию `labs`

## Что делает пайплайн

Пайплайн берет исходные `.docx` из `wiki/materials/sources`, извлекает из них текст, таблицы, формулы и изображения, после чего собирает итоговые markdown-материалы в `wiki/materials/curated`.

Результат для каждой ЛР:

- папка `wiki/materials/curated/<lab-slug>`
- `sections/*.md` — секции лабораторной
- `assets/*` — изображения и вложения
- `meta.yaml` — метаданные ЛР

## Где находится логика

Основная логика пайплайна находится в файле:

- `wiki/src/application/services/materials_pipeline.py`

## Что делает `meta.yaml`

`meta.yaml` — это сводка по лабораторной.

В нем хранятся:

- `lab_id`
- `slug`
- `title`
- `tags`
- исходный `source.file`
- `stats`
- список секций
- список assets

Он нужен как быстрый индекс ЛР без чтения всех markdown-файлов.

## Текущий режим работы

Сейчас используется режим `curated-first`:

- если для ЛР уже есть готовая папка в `curated`, пайплайн не пересобирает ее из Word
- если `curated` для ЛР нет, выполняется полная генерация из `sources`

Это позволяет сочетать автоматическую генерацию и ручную доработку финальных markdown-файлов.
