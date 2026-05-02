import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2, Power, PowerOff } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
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
import { Clients, Tunnels, type Client, type TunnelState, type VpnType } from '@/lib/api';
import { usePoll } from '@/lib/polling';

const VPN_TYPES: VpnType[] = ['openvpn', 'openconnect', 'openfortivpn', 'wireguard', 'strongswan'];

const STATE_VARIANT: Record<TunnelState, 'success' | 'warning' | 'destructive' | 'secondary'> = {
  up: 'success',
  starting: 'warning',
  down: 'warning',
  errored: 'destructive',
  stopped: 'secondary',
};

interface NewClientForm {
  id: string;
  name: string;
  vpn_type: VpnType;
  virtual_cidr: string;
  real_cidr: string;
  dns_server: string;
  config_text: string;
  vpn_username: string;
  vpn_password: string;
}

const EMPTY_FORM: NewClientForm = {
  id: '',
  name: '',
  vpn_type: 'openvpn',
  virtual_cidr: '',
  real_cidr: '',
  dns_server: '',
  config_text: '',
  vpn_username: '',
  vpn_password: '',
};

export function ClientsPage() {
  const { t } = useTranslation();
  const list = usePoll(Clients.list, 5_000);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<NewClientForm>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof NewClientForm>(k: K, v: NewClientForm[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const submitNew = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await Clients.create({
        ...form,
        dns_server: form.dns_server || null,
        vpn_username: form.vpn_username || null,
        vpn_password: form.vpn_password || null,
        config_text: form.config_text || null,
        nat_mappings: [],
      } as Partial<Client>);
      setShowCreate(false);
      setForm(EMPTY_FORM);
      await list.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const remove = async (id: string) => {
    if (!confirm(t('clients.delete_confirm'))) return;
    await Clients.remove(id);
    await list.refetch();
  };

  const connect = async (id: string) => {
    await Tunnels.connect(id);
    await list.refetch();
  };

  const disconnect = async (id: string) => {
    await Tunnels.disconnect(id);
    await list.refetch();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">{t('clients.title')}</h1>
        <Button onClick={() => setShowCreate((s) => !s)}>
          <Plus size={16} className="mr-2" />
          {t('clients.create')}
        </Button>
      </div>

      {showCreate && (
        <Card>
          <CardHeader>
            <CardTitle>{t('clients.create')}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={submitNew} className="grid gap-3 md:grid-cols-2">
              <Input
                placeholder={t('clients.id')}
                required
                value={form.id}
                onChange={(e) => set('id', e.target.value)}
              />
              <Input
                placeholder={t('clients.name')}
                required
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
              />
              <select
                className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={form.vpn_type}
                onChange={(e) => set('vpn_type', e.target.value as VpnType)}
              >
                {VPN_TYPES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
              <Input
                placeholder={t('clients.virtual_cidr')}
                required
                value={form.virtual_cidr}
                onChange={(e) => set('virtual_cidr', e.target.value)}
              />
              <Input
                placeholder={t('clients.real_cidr')}
                required
                value={form.real_cidr}
                onChange={(e) => set('real_cidr', e.target.value)}
              />
              <Input
                placeholder={t('clients.dns_server')}
                value={form.dns_server}
                onChange={(e) => set('dns_server', e.target.value)}
              />
              <Input
                placeholder={t('clients.username')}
                value={form.vpn_username}
                onChange={(e) => set('vpn_username', e.target.value)}
              />
              <Input
                type="password"
                placeholder={t('clients.password')}
                value={form.vpn_password}
                onChange={(e) => set('vpn_password', e.target.value)}
              />
              <textarea
                className="md:col-span-2 min-h-32 rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
                placeholder={t('clients.config_text')}
                value={form.config_text}
                onChange={(e) => set('config_text', e.target.value)}
              />
              {error && <p className="text-sm text-destructive md:col-span-2">{error}</p>}
              <div className="flex gap-2 md:col-span-2">
                <Button type="submit">{t('clients.save')}</Button>
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
            <p className="text-sm text-muted-foreground">{t('clients.no_clients')}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('clients.id')}</TableHead>
                  <TableHead>{t('clients.name')}</TableHead>
                  <TableHead>{t('clients.vpn_type')}</TableHead>
                  <TableHead>{t('clients.virtual_cidr')}</TableHead>
                  <TableHead>{t('clients.real_cidr')}</TableHead>
                  <TableHead>{t('clients.tunnel_state')}</TableHead>
                  <TableHead className="text-right">{t('clients.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(list.data ?? []).map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">{c.id}</TableCell>
                    <TableCell>{c.name}</TableCell>
                    <TableCell>{c.vpn_type}</TableCell>
                    <TableCell className="font-mono text-xs">{c.virtual_cidr}</TableCell>
                    <TableCell className="font-mono text-xs">{c.real_cidr}</TableCell>
                    <TableCell>
                      <Badge variant={STATE_VARIANT[c.tunnel_state]}>
                        {t(`clients.states.${c.tunnel_state}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="space-x-1 text-right">
                      {c.tunnel_state === 'stopped' || c.tunnel_state === 'errored' ? (
                        <Button size="icon" variant="ghost" onClick={() => connect(c.id)}>
                          <Power size={16} />
                        </Button>
                      ) : (
                        <Button size="icon" variant="ghost" onClick={() => disconnect(c.id)}>
                          <PowerOff size={16} />
                        </Button>
                      )}
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
