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
import { Consultants, type Consultant } from '@/lib/api';
import { usePoll } from '@/lib/polling';

interface NewConsultantForm {
  email: string;
  name: string;
  openvpn_username: string;
  static_pool_ip: string;
  role: 'viewer' | 'operator' | 'admin';
}

const EMPTY: NewConsultantForm = {
  email: '',
  name: '',
  openvpn_username: '',
  static_pool_ip: '',
  role: 'viewer',
};

export function ConsultantsPage() {
  const { t } = useTranslation();
  const list = usePoll(Consultants.list, 30_000);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<NewConsultantForm>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof NewConsultantForm>(k: K, v: NewConsultantForm[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const submitNew = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await Consultants.create({
        ...form,
        openvpn_username: form.openvpn_username || null,
        static_pool_ip: form.static_pool_ip || null,
      } as Partial<Consultant>);
      setForm(EMPTY);
      setShowCreate(false);
      await list.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const remove = async (id: number) => {
    if (!confirm(t('consultants.delete_confirm'))) return;
    await Consultants.remove(id);
    await list.refetch();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">{t('consultants.title')}</h1>
        <Button onClick={() => setShowCreate((s) => !s)}>
          <Plus size={16} className="mr-2" />
          {t('consultants.create')}
        </Button>
      </div>

      {showCreate && (
        <Card>
          <CardHeader>
            <CardTitle>{t('consultants.create')}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={submitNew} className="grid gap-3 md:grid-cols-2">
              <Input
                placeholder={t('consultants.email')}
                type="email"
                required
                value={form.email}
                onChange={(e) => set('email', e.target.value)}
              />
              <Input
                placeholder={t('consultants.name')}
                required
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
              />
              <Input
                placeholder={t('consultants.openvpn_username')}
                value={form.openvpn_username}
                onChange={(e) => set('openvpn_username', e.target.value)}
              />
              <Input
                placeholder={t('consultants.static_pool_ip')}
                value={form.static_pool_ip}
                onChange={(e) => set('static_pool_ip', e.target.value)}
              />
              <select
                className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={form.role}
                onChange={(e) => set('role', e.target.value as NewConsultantForm['role'])}
              >
                <option value="viewer">viewer</option>
                <option value="operator">operator</option>
                <option value="admin">admin</option>
              </select>
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
          {list.error && <p className="text-sm text-destructive">{list.error}</p>}
          {list.data && list.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('consultants.no_consultants')}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('consultants.email')}</TableHead>
                  <TableHead>{t('consultants.name')}</TableHead>
                  <TableHead>{t('consultants.openvpn_username')}</TableHead>
                  <TableHead>{t('consultants.static_pool_ip')}</TableHead>
                  <TableHead>{t('consultants.role')}</TableHead>
                  <TableHead>{t('consultants.active')}</TableHead>
                  <TableHead className="text-right">{t('common.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(list.data ?? []).map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>{c.email}</TableCell>
                    <TableCell>{c.name}</TableCell>
                    <TableCell className="font-mono text-xs">{c.openvpn_username ?? '—'}</TableCell>
                    <TableCell className="font-mono text-xs">{c.static_pool_ip ?? '—'}</TableCell>
                    <TableCell>{c.role}</TableCell>
                    <TableCell>{c.active ? t('common.yes') : t('common.no')}</TableCell>
                    <TableCell className="text-right">
                      <Button size="icon" variant="ghost" onClick={() => remove(c.id)}>
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
