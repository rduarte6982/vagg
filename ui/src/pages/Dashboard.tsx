import { useTranslation } from 'react-i18next';
import { Activity, ArrowUpRight, Cable, Network, ShieldCheck, Users } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeader } from '@/components/ui/page-header';
import { StatTile } from '@/components/ui/stat-tile';
import { StatusLed, type LedState } from '@/components/ui/status-led';
import { TopologyMap, type TopologyClient } from '@/components/ui/topology';
import { Audit, Clients, Consultants, System, type TunnelState } from '@/lib/api';
import { usePoll } from '@/lib/polling';

const TUNNEL_TO_LED: Record<TunnelState, LedState> = {
  up: 'on',
  starting: 'warn',
  down: 'warn',
  errored: 'error',
  stopped: 'off',
};

export function DashboardPage() {
  const { t } = useTranslation();
  const clients = usePoll(Clients.list, 5_000);
  const consultants = usePoll(Consultants.list, 30_000);
  const license = usePoll(System.license, 60_000);
  const recent = usePoll(() => Audit.list({ limit: 6 }), 15_000);
  const health = usePoll(System.health, 20_000);

  const totalClients = clients.data?.length ?? 0;
  const onlineClients = clients.data?.filter((c) => c.tunnel_state === 'up').length ?? 0;
  const erroredClients = clients.data?.filter((c) => c.tunnel_state === 'errored').length ?? 0;
  const activeConsultants = consultants.data?.filter((c) => c.active).length ?? 0;

  const topo: TopologyClient[] =
    clients.data?.map((c) => ({
      id: c.id,
      name: c.name,
      state: TUNNEL_TO_LED[c.tunnel_state],
      vpn_type: c.vpn_type,
    })) ?? [];

  // Distingue 3 estados: ainda carregando (data null, sem error) → off "neutro";
  // erro de rede ou status != ok → vermelho; warn quando há túneis com problema.
  const overallLed: LedState = health.error
    ? 'error'
    : health.data === null
      ? 'off'
      : health.data.status !== 'ok'
        ? 'error'
        : erroredClients > 0
          ? 'warn'
          : 'on';

  const overallLabel =
    overallLed === 'error'
      ? 'Aggregator inacessível'
      : overallLed === 'off'
        ? t('common.loading')
        : overallLed === 'warn'
          ? `${erroredClients} túnel(eis) com erro`
          : t('dashboard.internet_ok');

  return (
    <div>
      <PageHeader
        title={t('dashboard.title')}
        description={t('dashboard.subtitle')}
        actions={
          <div className="flex items-center gap-3 rounded-md border border-border bg-popover px-3 py-1.5 shadow-sm">
            <StatusLed state={overallLed} />
            <span className="text-xs font-medium text-foreground">{overallLabel}</span>
          </div>
        }
      />

      {/* Topology map */}
      <TopologyMap clients={topo} consultantsActive={activeConsultants} />

      {/* Stat tiles */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label={t('dashboard.consultants_active')}
          value={activeConsultants}
          hint={`${consultants.data?.length ?? 0} cadastrados`}
          icon={<Users size={18} />}
        />
        <StatTile
          label={t('dashboard.clients_online')}
          value={
            <>
              {onlineClients}
              <span className="ml-1 text-base text-muted-foreground">
                / {totalClients}
              </span>
            </>
          }
          hint={erroredClients > 0 ? `${erroredClients} com erro` : 'tudo certo'}
          tone={erroredClients > 0 ? 'warning' : 'success'}
          icon={<Network size={18} />}
        />
        <StatTile
          label={t('dashboard.tunnels_total')}
          value={totalClients}
          hint="VPNs gerenciadas"
          icon={<Cable size={18} />}
        />
        <StatTile
          label={t('dashboard.license_status')}
          value={
            <span className="text-lg font-semibold capitalize">
              {(license.data?.status as string) ?? '—'}
            </span>
          }
          hint={(license.data?.tier as string) ?? ''}
          icon={<ShieldCheck size={18} />}
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        {/* Lista resumida de túneis */}
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle>Túneis</CardTitle>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Status em tempo real (poll a cada 5s)
              </p>
            </div>
            <Link
              to="/clients"
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-primary hover:bg-secondary"
            >
              Ver todos <ArrowUpRight size={12} />
            </Link>
          </CardHeader>
          <CardContent className="px-0 py-0">
            {clients.data && clients.data.length === 0 ? (
              <p className="px-5 py-6 text-sm text-muted-foreground">
                {t('clients.no_clients')}
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {(clients.data ?? []).slice(0, 6).map((c) => (
                  <li
                    key={c.id}
                    className="flex items-center gap-3 px-5 py-3 transition-colors hover:bg-secondary/40"
                  >
                    <StatusLed state={TUNNEL_TO_LED[c.tunnel_state]} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{c.name}</p>
                      <p className="truncate text-[11px] text-muted-foreground">
                        {c.id} · {c.vpn_type} · {c.virtual_cidr} → {c.real_cidr}
                      </p>
                    </div>
                    <span className="hidden text-[11px] font-medium text-muted-foreground sm:inline">
                      {t(`clients.states.${c.tunnel_state}`)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        {/* Atividade recente */}
        <Card>
          <CardHeader>
            <CardTitle>{t('dashboard.recent_audit')}</CardTitle>
          </CardHeader>
          <CardContent className="px-0 py-0">
            {recent.data && recent.data.length === 0 ? (
              <p className="px-5 py-6 text-sm text-muted-foreground">
                {t('audit.no_events')}
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {(recent.data ?? []).slice(0, 6).map((e) => (
                  <li key={e.id} className="px-5 py-3">
                    <div className="flex items-center gap-2 text-sm">
                      <Activity size={13} className="text-muted-foreground" />
                      <span className="truncate font-medium">{e.event_type}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {new Date(e.occurred_at).toLocaleString()} ·{' '}
                      {e.actor_consultant_id ? `usuário #${e.actor_consultant_id}` : 'sistema'}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
