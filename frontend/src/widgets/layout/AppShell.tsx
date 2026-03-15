import { Link, useLocation, useNavigate } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "../../app/providers/AuthProvider";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [isLogoutModalOpen, setIsLogoutModalOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  async function confirmLogout() {
    setIsLoggingOut(true);
    await logout();
    setIsLoggingOut(false);
    setIsLogoutModalOpen(false);
    navigate("/login");
  }

  return (
    <>
      <div className="app-layout">
        <header className="app-nav">
          <div className="app-nav__logo">LMS</div>

          <nav className="app-nav__menu" aria-label="Navigation">
            <Link
              to="/assignments"
              className={`app-nav__link ${location.pathname.startsWith("/assignments") ? "app-nav__link--active" : ""}`}
            >
              Задания
            </Link>
            <Link
              to="/wiki"
              className={`app-nav__link ${location.pathname.startsWith("/wiki") ? "app-nav__link--active" : ""}`}
            >
              Wiki
            </Link>
          </nav>

          <button
            type="button"
            className="btn btn--outline-light"
            onClick={() => setIsLogoutModalOpen(true)}
          >
            Выход
          </button>
        </header>

        <main className="app-content">{children}</main>
      </div>

      {isLogoutModalOpen ? (
        <div className="logout-modal-backdrop" role="presentation">
          <div className="logout-modal" role="dialog" aria-modal="true" aria-labelledby="logout-title">
            <p className="logout-modal__eyebrow">Подтверждение</p>
            <h2 id="logout-title">Завершить текущую сессию?</h2>
            <p className="link-muted">Авторизация будет завершена на клиенте и сервере.</p>
            <div className="logout-modal__actions">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setIsLogoutModalOpen(false)}
                disabled={isLoggingOut}
              >
                Отмена
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={confirmLogout}
                disabled={isLoggingOut}
              >
                {isLoggingOut ? "Выходим..." : "Подтвердить выход"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

