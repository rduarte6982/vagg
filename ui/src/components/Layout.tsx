import { useTranslation } from 'react-i18next';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { LogOut, Moon, Sun } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth-context';
import { useTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';

interface NavItem {
  to: string;
  key: string;
  exact?: boolean;
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: '/', key: 'dashboard', exact: true },
  { to: '/clients', key: 'clients' },
  { to: '/consultants', key: 'consultants' },
  { to: '/policies', key: 'policies' },
  { to: '/audit', key: 'audit' },
  { to: '/system', key: 'system' },
];

export function Layout() {
  const { t, i18n } = useTranslation();
  const { theme, toggle } = useTheme();
  const { email, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const switchLang = () => {
    void i18n.changeLanguage(i18n.language.startsWith('pt') ? 'en' : 'pt-BR');
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b">
        <div className="container flex h-14 items-center justify-between">
          <Link to="/" className="font-semibold">
            {t('app.title')}
          </Link>
          <nav className="hidden gap-4 md:flex">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.key}
                to={item.to}
                end={item.exact}
                className={({ isActive }) =>
                  cn(
                    'text-sm transition-colors hover:text-primary',
                    isActive ? 'font-semibold text-primary' : 'text-muted-foreground',
                  )
                }
              >
                {t(`nav.${item.key}`)}
              </NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={switchLang} aria-label="language">
              {i18n.language.startsWith('pt') ? 'EN' : 'PT'}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={toggle}
              aria-label={theme === 'dark' ? t('nav.theme_light') : t('nav.theme_dark')}
            >
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </Button>
            {email && (
              <>
                <span className="hidden text-sm text-muted-foreground md:inline">{email}</span>
                <Button variant="ghost" size="icon" onClick={handleLogout} aria-label={t('nav.logout')}>
                  <LogOut size={18} />
                </Button>
              </>
            )}
          </div>
        </div>
        <nav className="container flex gap-4 overflow-x-auto pb-2 md:hidden">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.key}
              to={item.to}
              end={item.exact}
              className={({ isActive }) =>
                cn(
                  'whitespace-nowrap text-sm transition-colors hover:text-primary',
                  isActive ? 'font-semibold text-primary' : 'text-muted-foreground',
                )
              }
            >
              {t(`nav.${item.key}`)}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="container py-8">
        <Outlet />
      </main>
    </div>
  );
}
