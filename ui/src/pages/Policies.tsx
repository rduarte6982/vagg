import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, RefreshCw, ShieldPlus, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Modal } from '@/components/ui/modal';
import { PageHeader } from '@/components/ui/page-header';
import { Select } from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Clients, Consultants, Policies, type Policy } from '@/lib/api';
import { usePoll } from '@/lib/polling';

interface NewPolicyForm {
  consultant_id: number;
  client_id: string;
  scope_kind: 'full' | 'subnet' | 'host';
  scope_value: string;
}

export function PoliciesPage() {
  const { t } = useTranslation();
  const policies = usePoll(Policies.list, 30_000);
  const consultants = usePoll(Consultants.list, 60_000);
  const clients = usePoll(Clients.list, 60_000);

  const [form, setForm] = useState<NewPolicyForm>({
    consultant_id: 0,
    client_id: '',
    scope_kind: 'full',
    scope_value: '',
  });
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const set = <K extends keyof NewPolicyForm>(k: K, v: NewPolicyForm[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const submitNew = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await Policies.create({
        ...form,
        scope_value: form.scope_value || null,
      } as Partial<Policy>);
      setShowCreate(false);
      setForm({ consultant_id: 0, client_id: '', scope_kind: 'full', scope_value: '' });
      await policies.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const consultantById = new Map(consultants.data?.map((c) => [c.id, c]) ?? []);
  const clientById = new Map(clients.data?.map((c) => [c.id, c]) ?? []);

  return (
    <div>
      <PageHeader
        title={t('policies.title')}
        description={t('policies.subtitle')}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => policies.refetch()}>
              <RefreshCw size={14} className="mr-1.5" />
              {t('common.refresh')}
            </Button>
            <Button size="sm" onClick={() => setShowCreate(true)}>
              <ShieldPlus size={14} className="mr-1.5" />
              {t('policies.create')}
            </Button>
          </>
        }
      />

      <Card>
        <CardContent className="px-0 py-0">
          {policies.data && policies.data.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm text-muted-foreground">
              {t('policies.no_policies')}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('policies.consultant')}</TableHead>
                  <TableHead>{t('policies.client')}</TableHead>
                  <TableHead>{t('policies.scope_kind')}</TableHead>
                  <TableHead>{t('policies.scope_value')}</TableHead>
                  <TableHead>{t('policies.expires_at')}</TableHead>
                  <TableHead className="text-right">{t('common.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(policies.data ?? []).map((p) => {
                  const consultant = consultantById.get(p.consultant_id);
                  const client = clientById.get(p.client_id);
                  return (
                    <TableRow key={p.id}>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-medium">
                            {consultant?.name ?? `#${p.consultant_id}`}
                          </span>
                          {consultant?.email && (
                            <span className="text-[11px] text-muted-foreground">
                              {consultant.email}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-medium">{client?.name ?? p.client_id}</span>
                          <span className="text-[11px] text-muted-foreground">{p.client_id}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="info">{t(`policies.scope_kinds.${p.scope_kind}`)}</Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {p.scope_value ?? '—'}
                      </TableCell>
                      <TableCell className="text-xs">
                        {p.expires_at ? new Date(p.expires_at).toLocaleDateString() : '—'}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={async () => {
                            await Policies.remove(p.id);
                            await policies.refetch();
                          }}
                        >
                          <Trash2 size={14} />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title={t('policies.create')}
        description="Vincule um consultor a um cliente. Use 'host' ou 'subnet' para limitar o que ele pode alcançar."
        footer={
          <>
            <Button variant="outline" onClick={() => setShowCreate(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" form="policy-form">
              <Plus size={14} className="mr-1" />
              {t('common.save')}
            </Button>
          </>
        }
      >
        <form id="policy-form" onSubmit={submitNew} className="grid gap-4 md:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              {t('policies.consultant')}
            </span>
            <Select
              required
              value={form.consultant_id || ''}
              onChange={(e) => set('consultant_id', Number(e.target.value))}
            >
              <option value="">— escolher —</option>
              {(consultants.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.email})
                </option>
              ))}
            </Select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('policies.client')}</span>
            <Select
              required
              value={form.client_id}
              onChange={(e) => set('client_id', e.target.value)}
            >
              <option value="">— escolher —</option>
              {(clients.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} · {c.id}
                </option>
              ))}
            </Select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              {t('policies.scope_kind')}
            </span>
            <Select
              value={form.scope_kind}
              onChange={(e) => set('scope_kind', e.target.value as NewPolicyForm['scope_kind'])}
            >
              <option value="full">{t('policies.scope_kinds.full')}</option>
              <option value="subnet">{t('policies.scope_kinds.subnet')}</option>
              <option value="host">{t('policies.scope_kinds.host')}</option>
            </Select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              {t('policies.scope_value')}
            </span>
            <Input
              value={form.scope_value}
              onChange={(e) => set('scope_value', e.target.value)}
              placeholder={form.scope_kind === 'host' ? '10.10.5.42' : '10.10.5.0/24'}
              disabled={form.scope_kind === 'full'}
            />
          </label>
          {error && (
            <div className="md:col-span-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
              {error}
            </div>
          )}
        </form>
      </Modal>
    </div>
  );
}
