import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import { LogIn, ShieldCheck, Activity } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { VaggLogo } from '@/components/ui/vagg-logo';
import { useAuth } from '@/lib/auth-context';
import { isDemo } from '@/lib/demo';

interface FromState {
  from?: { pathname?: string };
}

export function LoginPage() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('admin');
  const [password, setPassword] = useState(isDemo() ? 'demo' : '');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      const next = (location.state as FromState | undefined)?.from?.pathname ?? '/';
      navigate(next, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('login.error'));
    } finally {
      setSubmitting(false);
    }
  };

  const enableDemo = () => {
    const url = new URL(window.location.href);
    url.searchParams.set('demo', '1');
    window.location.href = url.toString();
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background px-4 py-10">
      {/* Glow sutil em signal-green — único acento permitido pelo brand. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 overflow-hidden"
        style={{
          backgroundImage:
            'radial-gradient(circle at 25% 25%, rgba(52, 200, 150, 0.08), transparent 45%), radial-gradient(circle at 75% 70%, rgba(52, 200, 150, 0.05), transparent 50%)',
        }}
      />
      <div className="relative grid w-full max-w-4xl overflow-hidden rounded-xl border border-border bg-card shadow-pop md:grid-cols-2">
        {/* Painel esquerdo — brand panel preto */}
        <div className="hidden border-r border-border bg-background p-10 md:flex md:flex-col md:justify-between">
          <div>
            <VaggLogo size={36} showWordmark wordmarkSize="lg" />
            <p className="eyebrow mt-1.5 ml-12">console</p>
            <h2 className="display-mono mt-12 text-3xl font-semibold leading-tight">
              {t('app.tagline')}
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Mantenha túneis persistentes para todas as VPNs dos seus clientes.
              Os usuários conectam só no VAGG e ganham acesso imediato — sem
              cliente VPN específico no notebook.
            </p>
          </div>

          <div className="mt-10 space-y-3 text-sm">
            <div className="flex items-start gap-2.5">
              <span className="router-led router-led--on mt-1.5" />
              <p className="text-foreground/80">
                5 protocolos suportados — OpenVPN, WireGuard, IPSec, OpenConnect, OpenFortiVPN.
              </p>
            </div>
            <div className="flex items-start gap-2.5">
              <ShieldCheck size={15} className="mt-0.5 text-[var(--vagg-signal)]" />
              <p className="text-foreground/80">
                RBAC granular por usuário, audit trail hash-chained — pronto pra LGPD.
              </p>
            </div>
            <div className="flex items-start gap-2.5">
              <Activity size={15} className="mt-0.5 text-[var(--vagg-signal)]" />
              <p className="text-foreground/80">
                Self-hosted. Os dados do seu cliente final nunca saem da sua rede.
              </p>
            </div>
          </div>
        </div>

        {/* Form de login */}
        <div className="px-8 py-10 md:px-10">
          {/* Em mobile, a logo aparece em cima do form. */}
          <div className="mb-6 flex items-center md:hidden">
            <VaggLogo size={28} showWordmark />
          </div>
          <header className="mb-7">
            <p className="eyebrow">{t('app.subtitle')}</p>
            <h1 className="display-mono mt-1 text-2xl">{t('login.title')}</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {isDemo() ? t('login.hint_demo') : t('login.hint_default')}
            </p>
          </header>

          {!isDemo() && (
            <div className="mb-4 rounded-md border border-[var(--vagg-line-2)] bg-secondary px-3 py-2 text-xs text-muted-foreground">
              <strong className="text-foreground">Primeira vez?</strong>{' '}
              use{' '}
              <code className="rounded bg-popover px-1 font-mono text-[var(--vagg-signal)]">
                admin
              </code>{' '}
              /{' '}
              <code className="rounded bg-popover px-1 font-mono text-[var(--vagg-signal)]">
                admin
              </code>
              . Troque depois em <em>Sistema</em>.
            </div>
          )}

          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="username" className="text-xs font-medium text-muted-foreground">
                {t('login.email')}
              </label>
              <Input
                id="username"
                type="text"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="password" className="text-xs font-medium text-muted-foreground">
                {t('login.password')}
              </label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
                {error}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={submitting}>
              <LogIn size={15} className="mr-2" />
              {submitting ? t('login.submitting') : t('login.submit')}
            </Button>
          </form>

          {!isDemo() && (
            <div className="mt-6 rounded-md border border-dashed border-border bg-secondary/40 px-4 py-3 text-xs text-muted-foreground">
              <p className="mb-1 font-medium text-foreground">
                Sem agregador rodando?
              </p>
              Você pode explorar em{' '}
              <button
                type="button"
                onClick={enableDemo}
                className="font-medium text-[var(--vagg-signal)] hover:underline"
              >
                modo demonstração
              </button>{' '}
              — dados em memória.
            </div>
          )}

          <p className="mt-8 text-center font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/70">
            v0.1.0 · apache-2.0
          </p>
        </div>
      </div>
    </div>
  );
}
