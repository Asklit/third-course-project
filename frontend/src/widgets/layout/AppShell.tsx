import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../app/providers/AuthProvider";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div className="app-layout">
      <header className="app-nav">
        <div className="app-nav__logo">LMS</div>

        <nav className="app-nav__menu" aria-label="Навигация">
          <Link
            to="/assignments"
            className={`app-nav__link ${location.pathname.startsWith("/assignments") ? "app-nav__link--active" : ""}`}
          >
            Задания
          </Link>
        </nav>

        <button
          type="button"
          className="btn btn--outline-light"
          onClick={() => {
            logout();
            navigate("/login");
          }}
        >
          Выйти
        </button>
      </header>

      <main className="app-content">{children}</main>
    </div>
  );
}

