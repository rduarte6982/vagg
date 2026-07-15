import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Download, RefreshCcw, RotateCcw, Server } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeader } from '@/components/ui/page-header';
import { StatusLed } from '@/components/ui/status-led';
import { Demo, isDemo } from '@/lib/demo';
import { System } from '@/lib/api';
import { usePoll } from '@/lib/polling';

type DownloadEntry = { name: string; href: string; size?: string; modified?: string };

// nginx autoindex retorna HTML simples — parseamos os <a href=...> pra montar a
// lista de binários disponíveis. Usamos DOMParser pra evitar regex frágil.
async function fetchDownloads(): Promise<DownloadEntry[]> {
  const res = await fetch('/downloads/', { credentials: 'omit' });
  if (!res.ok) return [];
  const html = await res.text();
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const lines = doc.body.textContent?.split('\n') ?? [];
  const entries: DownloadEntry[] = [];
  for (const a of doc.querySelectorAll('a')) {
    const href = a.getAttribute('href') ?? '';
    const name = a.textContent?.trim() ?? '';
    if (!name || name === '../' || name.endsWith('/')) continue;
    // Tenta achar a linha do autoindex que contém esse nome pra extrair data/size.
    const meta = lines.find((l) => l.startsWith(name) || l.includes(`>${name}<`));
    let modified: string | undefined;
    let size: string | undefined;
    if (meta) {
      const trailing = meta.slice(meta.indexOf(name) + name.length).trim();
      const parts = trailing.split(/\s{2,}/).filter(Boolean);
      if (parts.length >= 2) {
        modified = parts[0];
        size = parts[1];
      }
    }
    entries.push({ name, href: `/downloads/${encodeURIComponent(href)}`, size, modified });
  }
  return entries;
}

export function SystemPage() {
  const { t } = useTranslation();
  const version = usePoll(System.version, 60_000);
  const license = usePoll(System.license, 60_000);
  const health = usePoll(System.health, 30_000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [downloads, setDownloads] = useState<DownloadEntry[]>([]);
  const [downloadsErr, setDownloadsErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchDownloads()
      .then((entries) => {
        if (alive) setDownloads(entries);
      })
      .catch((err) => {
        if (alive) setDownloadsErr(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, []);

  const regenerate = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const out = await System.dnsRegenerate();
      setMsg(`${t('system.regenerated')} (${out.corefile_bytes} bytes)`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const resetDemo = () => {
    Demo.resetState();
    location.reload();
  };

  const exitDemo = () => {
    const url = new URL(window.location.href);
    url.searchParams.set('demo', '0');
    localStorage.removeItem('vagg.demo');
    window.location.href = url.toString();
  };

  const healthLed: 'on' | 'off' | 'error' = health.error
    ? 'error'
    : health.data === null
      ? 'off'
      : health.data.status === 'ok'
        ? 'on'
        : 'error';
  const healthLabel =
    healthLed === 'on'
      ? t('system.uptime')
      : healthLed === 'off'
        ? t('common.loading')
        : t('common.error');

  return (
    <div>
      <PageHeader
        title={t('system.title')}
        description={t('system.subtitle')}
        actions={
          <div className="flex items-center gap-3 rounded-md border border-border bg-popover px-3 py-1.5 shadow-sm">
            <StatusLed state={healthLed} />
            <span className="text-xs font-medium">{healthLabel}</span>
          </div>
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server size={15} className="text-primary" />
              {t('system.version')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-sm">{version.data?.version ?? '—'}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {t('system.endpoint')}: {window.location.origin}/api/v1
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle2 size={15} className="text-router-led-on" />
              {t('system.health')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-sm">{health.data?.status ?? '—'}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t('system.license')}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-1 text-xs">
              {license.data &&
                Object.entries(license.data).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd className="font-mono">{String(v)}</dd>
                  </div>
                ))}
              {!license.data && <p className="text-muted-foreground">—</p>}
            </dl>
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>VAGG Client</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            Os usuários (consultores) instalam o <strong>VAGG Client</strong> no
            Windows, fazem login com suas credenciais corporativas, e o app
            mantém as rotas das VPNs ativas em sincronia automática com este
            servidor — sem comandos de PowerShell, sem distribuir scripts.
          </p>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <p>
            Quando o admin <strong>cadastra um cliente novo</strong> ou
            <strong> ajusta políticas</strong>, o VAGG Client de cada usuário
            autorizado adiciona/remove as rotas correspondentes no Windows na
            próxima sincronização (a cada 30 s, ou imediatamente via push).
          </p>

          <div className="rounded-md border border-border bg-secondary/40 p-3">
            <div className="mb-2 flex items-center gap-2">
              <Download size={14} className="text-primary" />
              <span className="text-xs font-semibold uppercase tracking-wide text-foreground">
                Instaladores disponíveis
              </span>
            </div>
            {downloadsErr && (
              <p className="text-xs text-muted-foreground">
                Diretório de downloads não disponível ({downloadsErr}). Coloque
                os binários em <code>/var/lib/vagg/downloads/</code> no servidor.
              </p>
            )}
            {!downloadsErr && downloads.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Nenhum binário publicado ainda. Faça <code>scp</code> do{' '}
                <code>vagg-client-setup-*.exe</code> pra{' '}
                <code>/var/lib/vagg/downloads/</code> no servidor.
              </p>
            )}
            {downloads.length > 0 && (
              <ul className="divide-y divide-border">
                {downloads.map((f) => (
                  <li
                    key={f.name}
                    className="flex items-center justify-between gap-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-mono text-xs">{f.name}</p>
                      <p className="text-[10px] text-muted-foreground">
                        {[f.size, f.modified].filter(Boolean).join(' · ') || ''}
                      </p>
                    </div>
                    <a
                      href={f.href}
                      download
                      className="inline-flex items-center gap-1 rounded-md border border-border bg-popover px-2.5 py-1 text-xs font-medium text-primary shadow-sm hover:bg-secondary"
                    >
                      <Download size={12} />
                      Baixar
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <p className="text-xs text-muted-foreground">
            Endpoint que o client consome:{' '}
            <code>{window.location.origin}/api/v1/me/routes</code>.
          </p>
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>DNS</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Reescreve o Corefile a partir do estado dos clientes e recarrega o
            CoreDNS para aplicar imediatamente.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={regenerate} disabled={busy}>
              <RefreshCcw size={14} className={`mr-1.5 ${busy ? 'animate-spin' : ''}`} />
              {t('system.regenerate_dns')}
            </Button>
            {msg && <p className="text-xs text-muted-foreground">{msg}</p>}
          </div>
        </CardContent>
      </Card>

      {isDemo() && (
        <Card className="mt-6 border-amber-200 bg-amber-50">
          <CardHeader>
            <CardTitle className="text-amber-900">Modo demonstração ativo</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-amber-900/80">
              Os dados desta sessão são apenas exemplos em memória.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={resetDemo}>
                <RotateCcw size={14} className="mr-1.5" />
                Recriar dados de exemplo
              </Button>
              <Button variant="outline" size="sm" onClick={exitDemo}>
                {t('common.exit_demo')}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
