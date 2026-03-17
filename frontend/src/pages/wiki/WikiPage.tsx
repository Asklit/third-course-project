import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchWikiLabs } from "../../entities/wiki/api/fetchWikiLabs";
import { searchWiki } from "../../entities/wiki/api/searchWiki";
import type { WikiLabSummary, WikiSearchHit } from "../../entities/wiki/model/wiki";

const KIND_OPTIONS = [
  { value: "", label: "Все разделы" },
  { value: "goal", label: "Цель" },
  { value: "theory", label: "Теория" },
  { value: "task", label: "Задание" },
  { value: "variants", label: "Варианты" },
  { value: "report", label: "Отчет" },
  { value: "qa", label: "Вопросы" },
  { value: "content", label: "Материалы" },
];

export function WikiPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [labs, setLabs] = useState<WikiLabSummary[]>([]);
  const [results, setResults] = useState<WikiSearchHit[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchLoading, setSearchLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const q = searchParams.get("q") ?? "";
  const tag = searchParams.get("tag") ?? "";
  const kind = searchParams.get("kind") ?? "";
  const labSlug = searchParams.get("lab") ?? "";

  useEffect(() => {
    async function loadLabs() {
      try {
        const data = await fetchWikiLabs();
        setLabs(data);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить wiki");
      } finally {
        setLoading(false);
      }
    }

    void loadLabs();
  }, []);

  useEffect(() => {
    async function loadSearch() {
      setSearchLoading(true);
      try {
        const data = await searchWiki({
          q,
          tag: tag || undefined,
          kind: kind || undefined,
          lab_slug: labSlug || undefined,
          limit: 50,
        });
        setResults(data.items);
        setError(null);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Не удалось выполнить поиск");
      } finally {
        setSearchLoading(false);
      }
    }

    void loadSearch();
  }, [q, tag, kind, labSlug]);

  const availableTags = useMemo(() => {
    const tags = new Set<string>();
    labs.forEach((lab) => lab.tags.forEach((item) => tags.add(item)));
    return Array.from(tags).sort((a, b) => a.localeCompare(b));
  }, [labs]);

  function onSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    const nextQ = String(form.get("q") ?? "").trim();
    const nextTag = String(form.get("tag") ?? "").trim();
    const nextKind = String(form.get("kind") ?? "").trim();
    const nextLab = String(form.get("lab") ?? "").trim();
    if (nextQ) {
      next.set("q", nextQ);
    }
    if (nextTag) {
      next.set("tag", nextTag);
    }
    if (nextKind) {
      next.set("kind", nextKind);
    }
    if (nextLab) {
      next.set("lab", nextLab);
    }
    setSearchParams(next);
  }

  return (
    <section className="stack">
      <article className="panel wiki-hero">
        <p className="eyebrow">Wiki</p>
        <h1>База материалов лабораторных</h1>
        <p className="meta">
          Здесь можно открыть лабораторную целиком или быстро найти конкретный фрагмент по ключевым словам,
          тегам и типу раздела.
        </p>
      </article>

      {loading ? <p>Загружаю базу wiki...</p> : null}
      {error ? <p className="error-text">{error}</p> : null}

      <article className="panel">
        <div className="wiki-section-head">
          <div>
            <p className="eyebrow">Раздел 1</p>
            <h2>Открыть лабораторную целиком</h2>
          </div>
          <p className="meta">Каждая карточка открывает полную wiki-страницу выбранной ЛР со всеми материалами подряд.</p>
        </div>

        <div className="wiki-labs-grid">
          {labs.map((lab) => (
            <Link className="wiki-lab-card" key={lab.slug} to={`/wiki/${lab.slug}`}>
              <h3>{lab.title}</h3>
              <p className="meta">Разделов: {lab.sections_count}</p>
              <p className="meta">Теги: {lab.tags.join(", ") || "—"}</p>
            </Link>
          ))}
        </div>
      </article>

      <form className="panel wiki-search-form" onSubmit={onSearchSubmit}>
        <div className="wiki-section-head">
          <div>
            <p className="eyebrow">Раздел 2</p>
            <h2>Поиск по материалам</h2>
          </div>
          <p className="meta">Найдите конкретный фрагмент по ключевым словам, тегам или типу раздела.</p>
        </div>

        <div className="field">
          <span className="field__label">Поисковый запрос</span>
          <input name="q" defaultValue={q} placeholder="Пример: рекурсия, console, LINQ, коллекции" />
        </div>

        <div className="wiki-search-form__grid wiki-search-form__grid--triple">
          <label className="field">
            <span className="field__label">Лабораторная</span>
            <select name="lab" defaultValue={labSlug}>
              <option value="">Все ЛР</option>
              {labs.map((lab) => (
                <option key={lab.slug} value={lab.slug}>
                  {lab.title}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span className="field__label">Тег</span>
            <select name="tag" defaultValue={tag}>
              <option value="">Все теги</option>
              {availableTags.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span className="field__label">Тип раздела</span>
            <select name="kind" defaultValue={kind}>
              {KIND_OPTIONS.map((option) => (
                <option key={option.value || "all"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="wiki-search-actions">
          <button className="btn btn--primary" type="submit">
            Найти
          </button>
          <button className="btn btn--ghost" type="button" onClick={() => setSearchParams(new URLSearchParams())}>
            Сбросить фильтры
          </button>
        </div>
      </form>

      {searchLoading ? <p>Выполняю поиск...</p> : null}

      <article className="panel">
        <h2>Результаты поиска ({results.length})</h2>
        {results.length === 0 ? (
          <p className="meta">Ничего не найдено. Попробуйте сократить запрос или убрать часть фильтров.</p>
        ) : null}

        <div className="wiki-search-results">
          {results.map((result, index) => (
            <Link
              key={`${result.lab_slug}-${result.section_id}-${index}`}
              className="wiki-search-card"
              to={`/wiki/${result.lab_slug}#${result.section_id}`}
            >
              <div className="wiki-search-card__head">
                <strong>{result.lab_title}</strong>
                <span className="status-chip status-chip--open">{result.kind}</span>
              </div>
              <p className="wiki-search-card__section">{result.section_title}</p>
              <p className="meta">{result.snippet}</p>
            </Link>
          ))}
        </div>
      </article>
    </section>
  );
}
