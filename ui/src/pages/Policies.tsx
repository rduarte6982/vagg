import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
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
      await policies.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const consultantById = new Map(consultants.data?.map((c) => [c.id, c]) ?? []);
  const clientById = new Map(clients.data?.map((c) => [c.id, c]) ?? []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">{t('policies.title')}</h1>
        <Button onClick={() => setShowCreate((s) => !s)}>
          <Plus size={16} className="mr-2" />
          {t('policies.create')}
        </Button>
      </div>

      {showCreate && (
        <Card>
          <CardHeader>
            <CardTitle>{t('policies.create')}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={submitNew} className="grid gap-3 md:grid-cols-2">
              <select
                className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
                required
                value={form.consultant_id || ''}
                onChange={(e) => set('consultant_id', Number(e.target.value))}
              >
                <option value="">{t('policies.consultant')}</option>
                {(consultants.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.email}
                  </option>
                ))}
              </select>
              <select
                className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
                required
                value={form.client_id}
                onChange={(e) => set('client_id', e.target.value)}
              >
                <option value="">{t('policies.client')}</option>
                {(clients.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id}
                  </option>
                ))}
              </select>
              <select
                className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={form.scope_kind}
                onChange={(e) => set('scope_kind', e.target.value as NewPolicyForm['scope_kind'])}
              >
                <option value="full">full</option>
                <option value="subnet">subnet</option>
                <option value="host">host</option>
              </select>
              <Input
                placeholder={t('policies.scope_value')}
                value={form.scope_value}
                onChange={(e) => set('scope_value', e.target.value)}
              />
              {error && <p className="text-sm text-destructive md:col-span-2">{error}</p>}
              <div className="flex gap-2 md:col-span-2">
                <Button type="submit">{t('common.save')}</Button>
                <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>
                  {t('common.cancel')}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="pt-6">
          {policies.data && policies.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('policies.no_policies')}</p>
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
                {(policies.data ?? []).map((p) => (
                  <TableRow key={p.id}>
                    <TableCell>
                      {consultantById.get(p.consultant_id)?.email ?? `#${p.consultant_id}`}
                    </TableCell>
                    <TableCell>{clientById.get(p.client_id)?.id ?? p.client_id}</TableCell>
                    <TableCell>{p.scope_kind}</TableCell>
                    <TableCell className="font-mono text-xs">{p.scope_value ?? '—'}</TableCell>
                    <TableCell>{p.expires_at ?? '—'}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={async () => {
                          await Policies.remove(p.id);
                          await policies.refetch();
                        }}
                      >
                        <Trash2 size={16} />
                      </Button>
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
