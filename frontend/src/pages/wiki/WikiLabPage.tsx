import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchWikiLabBySlug } from "../../entities/wiki/api/fetchWikiLabBySlug";
import type { WikiLabDetails } from "../../entities/wiki/model/wiki";
import { markdownToHtml, tryCopyMarkdownCode } from "../../shared/lib/markdown";

export function WikiLabPage() {
  const { slug } = useParams();
  const [lab, setLab] = useState<WikiLabDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) {
      setLoading(false);
      setError("Не передан slug материала");
      return;
    }

    const currentSlug = slug;

    async function load() {
      try {
        const data = await fetchWikiLabBySlug(currentSlug);
        setLab(data);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить wiki материал");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [slug]);

  const sectionHtml = useMemo(() => {
    if (!lab) {
      return [];
    }
    return lab.sections.map((section) => ({ id: section.id, title: section.title, html: markdownToHtml(section.content_md) }));
  }, [lab]);

  if (loading) {
    return <p>Загрузка материала...</p>;
  }

  if (error || !lab) {
    return <p className="error-text">{error ?? "Материал не найден"}</p>;
  }

  async function onMarkdownClick(event: React.MouseEvent<HTMLElement>) {
    const target = event.target as HTMLElement;
    const button = target.closest(".code-copy-btn") as HTMLButtonElement | null;
    if (!button) {
      return;
    }
    const code = button.dataset.code;
    if (!code) {
      return;
    }
    try {
      await tryCopyMarkdownCode(code);
      button.textContent = "Скопировано";
      window.setTimeout(() => {
        button.textContent = "Копировать";
      }, 1200);
    } catch {
      button.textContent = "Ошибка";
      window.setTimeout(() => {
        button.textContent = "Копировать";
      }, 1200);
    }
  }

  return (
    <section className="stack">
      <article className="panel wiki-hero">
        <Link to="/wiki" className="link-muted">
          Назад к wiki
        </Link>
        <h1>{lab.title}</h1>
        <p className="meta">Исходный файл: {lab.source_file}</p>
        <p className="meta">Найдено формул: {lab.stats?.equations_detected ?? 0}</p>
      </article>

      <article className="panel wiki-toc">
        <h2>Содержание</h2>
        <div className="wiki-toc__list">
          {lab.sections.map((section) => (
            <a key={section.id} href={`#${section.id}`} className="wiki-toc__link">
              {section.title}
            </a>
          ))}
        </div>
      </article>

      {sectionHtml.map((section) => (
        <article key={section.id} id={section.id} className="panel wiki-section">
          <h2>{section.title}</h2>
          <div className="markdown" onClick={onMarkdownClick} dangerouslySetInnerHTML={{ __html: section.html }} />
        </article>
      ))}
    </section>
  );
}
