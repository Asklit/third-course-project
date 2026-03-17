import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { fetchWikiLabBySlug } from "../../entities/wiki/api/fetchWikiLabBySlug";
import type { WikiLabDetails } from "../../entities/wiki/model/wiki";
import { markdownToHtml, tryCopyMarkdownCode } from "../../shared/lib/markdown";

function decodeHashSection(hash: string): string {
  if (!hash) {
    return "";
  }
  try {
    return decodeURIComponent(hash.replace(/^#/, ""));
  } catch {
    return hash.replace(/^#/, "");
  }
}

export function WikiLabPage() {
  const { slug } = useParams();
  const location = useLocation();
  const [lab, setLab] = useState<WikiLabDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSectionId, setActiveSectionId] = useState("");
  const sidebarNavRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!slug) {
      setLoading(false);
      setError("Не передан slug материала");
      return;
    }

    const currentSlug = slug;

    setLoading(true);
    setError(null);

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
    return lab.sections.map((section) => ({
      id: section.id,
      title: section.title,
      html: markdownToHtml(section.content_md),
    }));
  }, [lab]);

  useEffect(() => {
    if (!sectionHtml.length) {
      return;
    }

    const hashSectionId = decodeHashSection(location.hash);
    const initialSectionId = hashSectionId || sectionHtml[0]?.id || "";
    setActiveSectionId(initialSectionId);

    if (!hashSectionId) {
      return;
    }

    const scrollToTarget = () => {
      const target = document.getElementById(hashSectionId);
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    };

    window.requestAnimationFrame(() => {
      window.setTimeout(scrollToTarget, 80);
    });
  }, [location.hash, sectionHtml]);

  useEffect(() => {
    if (!sectionHtml.length) {
      return;
    }

    const sectionIds = sectionHtml.map((section) => section.id);
    let frameId = 0;

    const updateActiveSection = () => {
      frameId = 0;
      const offset = 148;
      let currentId = sectionIds[0] ?? "";
      let bestFallbackId = currentId;

      for (const sectionId of sectionIds) {
        const node = document.getElementById(sectionId);
        if (!node) {
          continue;
        }
        const rect = node.getBoundingClientRect();

        if (rect.top <= offset && rect.bottom > offset) {
          currentId = sectionId;
          break;
        }

        if (rect.top <= offset) {
          bestFallbackId = sectionId;
          continue;
        }

        if (rect.top > offset) {
          currentId = bestFallbackId;
          break;
        }
      }

      const lastSectionId = sectionIds[sectionIds.length - 1];
      const lastSectionNode = lastSectionId ? document.getElementById(lastSectionId) : null;
      if (lastSectionNode) {
        const lastRect = lastSectionNode.getBoundingClientRect();
        if (lastRect.top <= window.innerHeight * 0.65) {
          currentId = lastSectionId;
        }
      }

      if (currentId) {
        setActiveSectionId((previous) => (previous === currentId ? previous : currentId));
      }
    };

    const onScroll = () => {
      if (frameId) {
        return;
      }
      frameId = window.requestAnimationFrame(updateActiveSection);
    };

    updateActiveSection();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);

    return () => {
      if (frameId) {
        window.cancelAnimationFrame(frameId);
      }
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [sectionHtml]);

  useEffect(() => {
    if (!activeSectionId || !sidebarNavRef.current) {
      return;
    }

    const activeLink = sidebarNavRef.current.querySelector<HTMLElement>(`[data-section-link="${CSS.escape(activeSectionId)}"]`);
    if (!activeLink) {
      return;
    }

    const nav = sidebarNavRef.current;
    const midpoint = nav.clientHeight * 0.5;
    const upperThreshold = nav.clientHeight * 0.2;
    const activeTop = activeLink.offsetTop - nav.scrollTop;
    const activeBottom = activeTop + activeLink.offsetHeight;

    if (activeBottom > midpoint || activeTop < upperThreshold) {
      const nextScrollTop = Math.max(0, activeLink.offsetTop - nav.clientHeight * 0.35);
      nav.scrollTo({ top: nextScrollTop, behavior: "smooth" });
    }
  }, [activeSectionId]);

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

  if (loading) {
    return <p>Загрузка материала...</p>;
  }

  if (error || !lab) {
    return <p className="error-text">{error ?? "Материал не найден"}</p>;
  }

  return (
    <section className="stack">
      <article className="panel wiki-hero">
        <Link to="/wiki" className="link-muted">
          Назад к wiki
        </Link>
        <h1>{lab.title}</h1>
        <p className="meta">Исходный файл: {lab.source_file}</p>
      </article>

      <div className="wiki-layout">
        <aside className="panel wiki-sidebar">
          <div className="wiki-sidebar__head">
            <p className="eyebrow">Навигация</p>
            <h2>Разделы ЛР</h2>
          </div>
          <nav
            ref={sidebarNavRef}
            className="wiki-sidebar__nav"
            aria-label="Навигация по разделам лабораторной"
          >
            {lab.sections.map((section, index) => {
              const isActive = activeSectionId === section.id;
              return (
                <a
                  key={section.id}
                  data-section-link={section.id}
                  href={`#${section.id}`}
                  title={section.title}
                  className={`wiki-sidebar__link${isActive ? " wiki-sidebar__link--active" : ""}`}
                  onClick={() => setActiveSectionId(section.id)}
                >
                  <span className="wiki-sidebar__index">{String(index + 1).padStart(2, "0")}</span>
                  <span>{section.title}</span>
                </a>
              );
            })}
          </nav>
        </aside>

        <div className="wiki-content">
          {sectionHtml.map((section) => (
            <article key={section.id} id={section.id} className="panel wiki-section">
              <h2>{section.title}</h2>
              <div className="markdown" onClick={onMarkdownClick} dangerouslySetInnerHTML={{ __html: section.html }} />
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
