import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { System } from '@/lib/api';
import { usePoll } from '@/lib/polling';

export function SystemPage() {
  const { t } = useTranslation();
  const version = usePoll(System.version, 60_000);
  const license = usePoll(System.license, 60_000);
  const health = usePoll(System.health, 30_000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

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

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">{t('system.title')}</h1>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('system.version')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-sm">{version.data?.version ?? '—'}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('system.health')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-sm">{health.data?.status ?? '—'}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('system.license')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-sm">
              {(license.data?.status as string) ?? '—'}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">DNS</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Button onClick={regenerate} disabled={busy}>
            {t('system.regenerate_dns')}
          </Button>
          {msg && <p className="text-sm">{msg}</p>}
        </CardContent>
      </Card>
    </div>
  );
}
