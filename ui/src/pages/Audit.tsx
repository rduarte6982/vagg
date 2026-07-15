import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity, Download, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/ui/page-header';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Audit, type AuditEvent } from '@/lib/api';
import { usePoll } from '@/lib/polling';

function downloadFile(name: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function toCsv(events: AuditEvent[]): string {
  const header = ['id', 'event_type', 'actor_consultant_id', 'occurred_at', 'hash', 'payload'];
  const rows = events.map((e) =>
    [
      e.id,
      e.event_type,
      e.actor_consultant_id ?? '',
      e.occurred_at,
      e.hash,
      JSON.stringify(e.payload ?? {}).replace(/"/g, '""'),
    ]
      .map((v) => `"${String(v)}"`)
      .join(','),
  );
  return [header.join(','), ...rows].join('\n');
}

function eventColor(eventType: string): string {
  if (eventType.includes('error') || eventType.includes('fail') || eventType.includes('deny'))
    return 'text-destructive';
  if (eventType.startsWith('tunnel.connect')) return 'text-[#2f7a2f]';
  if (eventType.startsWith('auth.')) return 'text-info';
  return 'text-foreground';
}

export function AuditPage() {
  const { t } = useTranslation();
  const [eventType, setEventType] = useState('');
  const events = usePoll(
    () => Audit.list({ event_type: eventType || undefined, limit: 200 }),
    30_000,
  );

  const filtered = useMemo(() => events.data ?? [], [events.data]);

  return (
    <div>
      <PageHeader
        title={t('audit.title')}
        description={t('audit.subtitle')}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => events.refetch()}>
              <RefreshCw size={14} className="mr-1.5" />
              {t('common.refresh')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => downloadFile('audit.csv', toCsv(filtered), 'text/csv;charset=utf-8;')}
            >
              <Download size={14} className="mr-1.5" />
              CSV
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                downloadFile('audit.json', JSON.stringify(filtered, null, 2), 'application/json')
              }
            >
              <Download size={14} className="mr-1.5" />
              JSON
            </Button>
          </>
        }
      />

      <Card>
        <CardContent className="px-0 py-0">
          <div className="flex items-center gap-3 border-b border-border px-5 py-3">
            <Input
              placeholder={t('audit.filter_event_type')}
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              className="max-w-sm"
            />
            <span className="text-xs text-muted-foreground">{filtered.length} evento(s)</span>
          </div>
          {events.error && (
            <p className="px-5 py-3 text-sm text-destructive">{events.error}</p>
          )}
          {filtered.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm text-muted-foreground">
              {t('audit.no_events')}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('audit.occurred_at')}</TableHead>
                  <TableHead>{t('audit.event_type')}</TableHead>
                  <TableHead>{t('audit.actor')}</TableHead>
                  <TableHead>{t('audit.payload')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="font-mono text-[11px] text-muted-foreground">
                      {new Date(e.occurred_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <span className="inline-flex items-center gap-1.5">
                        <Activity size={12} className="text-muted-foreground" />
                        <span className={`font-medium ${eventColor(e.event_type)}`}>
                          {e.event_type}
                        </span>
                      </span>
                    </TableCell>
                    <TableCell>
                      {e.actor_consultant_id ? (
                        <span className="rounded-sm bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-primary">
                          usuário #{e.actor_consultant_id}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">sistema</span>
                      )}
                    </TableCell>
                    <TableCell className="max-w-md truncate font-mono text-[11px] text-muted-foreground">
                      {JSON.stringify(e.payload ?? {})}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
