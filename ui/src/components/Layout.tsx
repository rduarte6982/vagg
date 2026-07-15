import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  Activity,
  ChevronDown,
  Globe,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  Server,
  ShieldCheck,
  Users,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { VaggLogo } from '@/components/ui/vagg-logo';
import { useAuth } from '@/lib/auth-context';
import { isDemo } from '@/lib/demo';
import { cn } from '@/lib/utils';

interface NavItem {
  to: string;
  key: string;
  icon: typeof LayoutDashboard;
  exact?: boolean;
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: '/', key: 'dashboard', icon: LayoutDashboard, exact: true },
  { to: '/clients', key: 'clients', icon: Network },
  { to: '/consultants', key: 'consultants', icon: Users },
  { to: '/policies', key: 'policies', icon: ShieldCheck },
  { to: '/audit', key: 'audit', icon: Activity },
  { to: '/system', key: 'system', icon: Server },
];

export function Layout() {
  const { t, i18n } = useTranslation();
  const { email, role, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const switchLang = () => {
    void i18n.changeLanguage(i18n.language.startsWith('pt') ? 'en' : 'pt-BR');
  };

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      {/* Top bar — chrome escuro tipo TP-Link Omada */}
      <header
        className="flex h-14 shrink-0 items-center justify-between border-b border-router-header/40 px-4 text-router-header-text"
        style={{ background: 'var(--router-header-bg)' }}
      >
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setMobileOpen((o) => !o)}
            className="flex h-9 w-9 items-center justify-center rounded-md text-router-header-text/80 hover:bg-white/10 lg:hidden"
            aria-label="menu"
          >
            {mobileOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
          <Link to="/" className="flex items-center gap-3">
            <VaggLogo size={26} showWordmark wordmarkSize="md" />
            <span className="hidden text-[10px] uppercase tracking-[0.18em] text-router-header-muted md:inline">
              console
            </span>
          </Link>
        </div>
        <div className="flex items-center gap-2">
          {isDemo() && (
            <span className="hidden items-center gap-1.5 rounded-full bg-amber-500/20 px-2.5 py-1 text-[11px] font-medium text-amber-200 ring-1 ring-amber-300/30 sm:inline-flex">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-300" /> modo demonstração
            </span>
          )}
          <button
            type="button"
            onClick={switchLang}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-router-header-text/85 hover:bg-white/10"
            aria-label="language"
          >
            <Globe size={14} />
            {i18n.language.startsWith('pt') ? 'PT-BR' : 'EN'}
          </button>
          {email && (
            <div className="group relative">
              <button className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs font-medium hover:bg-white/10">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/80 text-[11px] font-semibold uppercase text-white">
                  {email.slice(0, 2)}
                </span>
                <span className="hidden flex-col items-start leading-tight sm:flex">
                  <span className="text-router-header-text">{email}</span>
                  <span className="text-[10px] uppercase tracking-wide text-router-header-muted">
                    {role ?? 'admin'}
                  </span>
                </span>
                <ChevronDown size={14} className="text-router-header-muted" />
              </button>
              <div className="invisible absolute right-0 top-full z-30 mt-1 w-48 rounded-md border border-border bg-popover p-1 text-foreground opacity-0 shadow-pop transition-all group-hover:visible group-hover:opacity-100">
                <div className="border-b border-border px-3 py-2 text-xs">
                  <p className="font-medium text-foreground">{email}</p>
                  <p className="text-muted-foreground">{role ?? 'admin'}</p>
                </div>
                <button
                  className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-xs text-foreground hover:bg-secondary"
                  onClick={handleLogout}
                >
                  <LogOut size={14} /> {t('nav.logout')}
                </button>
              </div>
            </div>
          )}
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside
          className={cn(
            'flex w-60 shrink-0 flex-col border-r border-border bg-router-sidebar transition-all',
            'fixed inset-y-14 z-30 lg:static lg:inset-y-0',
            mobileOpen ? 'left-0' : '-left-64 lg:left-0',
          )}
        >
          <nav className="flex-1 space-y-0.5 p-3">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.key}
                  to={item.to}
                  end={item.exact}
                  onClick={() => setMobileOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-secondary text-primary'
                        : 'text-muted-foreground hover:bg-secondary/60 hover:text-foreground',
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon size={16} className={isActive ? 'text-primary' : ''} />
                      <span>{t(`nav.${item.key}`)}</span>
                      {isActive && (
                        <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary" />
                      )}
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>
          <div className="border-t border-border bg-secondary/40 px-4 py-3 text-[11px] text-muted-foreground">
            <div className="flex items-center justify-between">
              <span>Status</span>
              <span className="flex items-center gap-1">
                <span className="router-led router-led--on" /> Online
              </span>
            </div>
            <p className="mt-1 truncate">vagg-core · localhost</p>
          </div>
        </aside>

        {mobileOpen && (
          <div
            className="fixed inset-0 z-20 bg-slate-900/40 lg:hidden"
            onClick={() => setMobileOpen(false)}
          />
        )}

        {/* Conteúdo */}
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-7xl px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

// O botão Button é importado para compatibilidade com testes legados que possam
// referenciar export deste módulo. Mantemos um re-export silencioso.
export { Button };
