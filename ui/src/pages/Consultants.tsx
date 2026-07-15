import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { KeyRound, Pencil, Plus, RefreshCw, Trash2, UserPlus } from 'lucide-react';
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
import { Consultants, type Consultant } from '@/lib/api';
import { usePoll } from '@/lib/polling';

type Role = 'viewer' | 'operator' | 'admin';

interface ConsultantForm {
  email: string;
  name: string;
  password: string; // só usado em CREATE; em EDIT é "" e ignorado
  role: Role;
  active: boolean;
}

const EMPTY: ConsultantForm = {
  email: '',
  name: '',
  password: '',
  role: 'viewer',
  active: true,
};

const ROLE_VARIANT: Record<Role, 'success' | 'info' | 'secondary'> = {
  admin: 'success',
  operator: 'info',
  viewer: 'secondary',
};

export function ConsultantsPage() {
  const { t } = useTranslation();
  const list = usePoll(Consultants.list, 30_000);

  // Modal de cadastro/edição (compartilha o form, mas em modo `editing` faz PATCH).
  const [editing, setEditing] = useState<Consultant | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<ConsultantForm>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Modal separado só pra senha (mais simples — o admin pode resetar sem
  // passar por todo o form de edição).
  const [pwModal, setPwModal] = useState<Consultant | null>(null);
  const [newPw, setNewPw] = useState('');
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwBusy, setPwBusy] = useState(false);

  useEffect(() => {
    if (showForm && editing) {
      setForm({
        email: editing.email,
        name: editing.name,
        password: '', // sempre vazio — não pode reler a senha
        role: editing.role,
        active: editing.active,
      });
    } else if (showForm && !editing) {
      setForm(EMPTY);
    }
  }, [showForm, editing]);

  const set = <K extends keyof ConsultantForm>(k: K, v: ConsultantForm[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const closeForm = () => {
    setShowForm(false);
    setEditing(null);
    setForm(EMPTY);
    setError(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (editing) {
        await Consultants.update(editing.id, {
          email: form.email,
          name: form.name,
          role: form.role,
          active: form.active,
        });
        // Se o admin escreveu uma senha nova no campo enquanto editava, atualiza.
        if (form.password.trim().length >= 4) {
          await Consultants.setPassword(editing.id, form.password.trim());
        }
      } else {
        await Consultants.create({
          email: form.email,
          name: form.name,
          password: form.password || undefined,
          role: form.role,
          active: form.active,
        });
      }
      closeForm();
      await list.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    if (!confirm(t('consultants.delete_confirm'))) return;
    await Consultants.remove(id);
    await list.refetch();
  };

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pwModal) return;
    setPwError(null);
    setPwBusy(true);
    try {
      await Consultants.setPassword(pwModal.id, newPw);
      setPwModal(null);
      setNewPw('');
      await list.refetch();
    } catch (err) {
      setPwError(err instanceof Error ? err.message : String(err));
    } finally {
      setPwBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title={t('consultants.title')}
        description={t('consultants.subtitle')}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => list.refetch()}>
              <RefreshCw size={14} className="mr-1.5" />
              {t('common.refresh')}
            </Button>
            <Button
              size="sm"
              onClick={() => {
                setEditing(null);
                setShowForm(true);
              }}
            >
              <UserPlus size={14} className="mr-1.5" />
              {t('consultants.create')}
            </Button>
          </>
        }
      />

      <Card>
        <CardContent className="px-0 py-0">
          {list.error && (
            <p className="px-5 py-3 text-sm text-destructive">{list.error}</p>
          )}
          {list.data && list.data.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm text-muted-foreground">
              {t('consultants.no_consultants')}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('consultants.name')}</TableHead>
                  <TableHead>{t('consultants.email')}</TableHead>
                  <TableHead>{t('consultants.password')}</TableHead>
                  <TableHead>{t('consultants.role')}</TableHead>
                  <TableHead>{t('consultants.active')}</TableHead>
                  <TableHead className="text-right">{t('common.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(list.data ?? []).map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary text-[11px] font-semibold uppercase text-primary">
                          {c.name.slice(0, 2)}
                        </span>
                        <span className="font-medium text-foreground">{c.name}</span>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{c.email}</TableCell>
                    <TableCell>
                      {c.has_password ? (
                        <span className="router-pill router-pill--on">
                          <span className="router-led router-led--on h-1.5 w-1.5" />
                          {t('consultants.password_set')}
                        </span>
                      ) : (
                        <span className="router-pill router-pill--off">
                          <span className="router-led router-led--warn h-1.5 w-1.5" />
                          {t('consultants.password_missing')}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={ROLE_VARIANT[c.role]}>{t(`consultants.roles.${c.role}`)}</Badge>
                    </TableCell>
                    <TableCell>
                      {c.active ? (
                        <span className="router-pill router-pill--on">
                          <span className="router-led router-led--on h-1.5 w-1.5" />
                          {t('common.yes')}
                        </span>
                      ) : (
                        <span className="router-pill router-pill--off">
                          <span className="router-led router-led--off h-1.5 w-1.5" />
                          {t('common.no')}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => {
                          setEditing(c);
                          setShowForm(true);
                        }}
                        title={t('common.edit')}
                      >
                        <Pencil size={14} />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => {
                          setPwModal(c);
                          setNewPw('');
                          setPwError(null);
                        }}
                        title={t('consultants.set_password')}
                      >
                        <KeyRound size={14} />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => remove(c.id)}
                        title={t('common.delete')}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Modal
        open={showForm}
        onClose={closeForm}
        title={editing ? `${t('common.edit')} — ${editing.name}` : t('consultants.create')}
        description={
          editing ? t('consultants.edit_subtitle') : t('consultants.create_subtitle')
        }
        footer={
          <>
            <Button variant="outline" onClick={closeForm}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" form="consultant-form" disabled={busy}>
              <Plus size={14} className="mr-1" />
              {t('common.save')}
            </Button>
          </>
        }
      >
        <form id="consultant-form" onSubmit={submit} className="grid gap-4 md:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('consultants.email')}</span>
            <Input
              type="email"
              required
              value={form.email}
              onChange={(e) => set('email', e.target.value)}
              placeholder="paulo@consultoria.com"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('consultants.name')}</span>
            <Input
              required
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="rduarte"
            />
          </label>
          <label className="flex flex-col gap-1.5 md:col-span-2">
            <span className="text-xs font-medium text-muted-foreground">
              {t('consultants.password')}{' '}
              <span className="text-[10px] text-muted-foreground/70">
                ({editing ? t('consultants.password_hint_edit') : t('consultants.password_hint')})
              </span>
            </span>
            <Input
              type="password"
              minLength={4}
              value={form.password}
              onChange={(e) => set('password', e.target.value)}
              placeholder="•••••••"
              autoComplete="new-password"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('consultants.role')}</span>
            <Select
              value={form.role}
              onChange={(e) => set('role', e.target.value as Role)}
            >
              <option value="viewer">{t('consultants.roles.viewer')}</option>
              <option value="operator">{t('consultants.roles.operator')}</option>
              <option value="admin">{t('consultants.roles.admin')}</option>
            </Select>
          </label>
          <label className="flex items-center gap-2 self-end pb-2">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(e) => set('active', e.target.checked)}
            />
            <span className="text-xs font-medium text-muted-foreground">
              {t('consultants.active')}
            </span>
          </label>
          {error && (
            <div className="md:col-span-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
              {error}
            </div>
          )}
        </form>
      </Modal>

      <Modal
        open={!!pwModal}
        onClose={() => {
          setPwModal(null);
          setNewPw('');
          setPwError(null);
        }}
        title={pwModal ? `${t('consultants.set_password')} — ${pwModal.name}` : ''}
        description={t('consultants.set_password_subtitle')}
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => {
                setPwModal(null);
                setNewPw('');
              }}
            >
              {t('common.cancel')}
            </Button>
            <Button type="submit" form="consultant-pw-form" disabled={pwBusy || newPw.length < 4}>
              <KeyRound size={14} className="mr-1" />
              {t('common.save')}
            </Button>
          </>
        }
      >
        <form id="consultant-pw-form" onSubmit={submitPassword} className="space-y-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('consultants.new_password')}</span>
            <Input
              type="password"
              required
              minLength={4}
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              autoFocus
              autoComplete="new-password"
            />
          </label>
          {pwError && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
              {pwError}
            </div>
          )}
        </form>
      </Modal>
    </div>
  );
}
