import { type ReactNode } from 'react';

interface ShellProps {
  children: ReactNode;
}

/** Shell visual do portal — top bar VAGG dark + container centralizado. */
export function Shell({ children }: ShellProps) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__brand">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 28 28"
            className="app-header__brand-mark"
            aria-hidden
          >
            <circle cx="4" cy="4" r="2" fill="#b6bbc2" />
            <circle cx="24" cy="4" r="2" fill="#b6bbc2" />
            <circle cx="4" cy="24" r="2" fill="#b6bbc2" />
            <circle cx="24" cy="24" r="2" fill="#b6bbc2" />
            <path d="M4 4 L14 14" stroke="#7a808a" strokeWidth="1.4" fill="none" />
            <path d="M24 4 L14 14" stroke="#7a808a" strokeWidth="1.4" fill="none" />
            <path d="M4 24 L14 14" stroke="#7a808a" strokeWidth="1.4" fill="none" />
            <path d="M24 24 L14 14" stroke="#7a808a" strokeWidth="1.4" fill="none" />
            <rect x="10" y="10" width="8" height="8" rx="1.6" fill="oklch(78% 0.16 162)" />
          </svg>
          <div>
            <div className="vagg-wordmark app-header__brand-name">
              vagg<span className="dot">.</span>
            </div>
            <div className="app-header__brand-sub">portal · transparência</div>
          </div>
        </div>
        <div className="app-header__meta">
          <span>
            <span className="led" /> serviço operacional
          </span>
        </div>
      </header>
      <main className="app-main">
        <div className="container">{children}</div>
      </main>
    </div>
  );
}
