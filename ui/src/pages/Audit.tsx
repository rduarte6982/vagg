import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
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

export function AuditPage() {
  const { t } = useTranslation();
  const [eventType, setEventType] = useState('');
  const events = usePoll(() => Audit.list({ event_type: eventType || undefined, limit: 200 }), 30_000);

  const filtered = useMemo(() => events.data ?? [], [events.data]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">{t('audit.title')}</h1>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={() => events.refetch()}>
            <RefreshCw size={16} />
          </Button>
          <Button
            variant="outline"
            onClick={() =>
              downloadFile('audit.csv', toCsv(filtered), 'text/csv;charset=utf-8;')
            }
          >
            <Download size={16} className="mr-2" />
            {t('common.export_csv')}
          </Button>
          <Button
            variant="outline"
            onClick={() =>
              downloadFile(
                'audit.json',
                JSON.stringify(filtered, null, 2),
                'application/json',
              )
            }
          >
            <Download size={16} className="mr-2" />
            {t('common.export_json')}
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          <div className="mb-4 flex gap-2">
            <Input
              placeholder={t('audit.filter_event_type')}
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              className="max-w-sm"
            />
          </div>
          {events.error && <p className="text-sm text-destructive">{events.error}</p>}
          {filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('audit.no_events')}</p>
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
                    <TableCell className="font-mono text-xs">{e.occurred_at}</TableCell>
                    <TableCell>{e.event_type}</TableCell>
                    <TableCell>{e.actor_consultant_id ?? '—'}</TableCell>
                    <TableCell className="max-w-md truncate font-mono text-xs">
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
