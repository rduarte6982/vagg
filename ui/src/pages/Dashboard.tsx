import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Clients, Consultants, System } from '@/lib/api';
import { usePoll } from '@/lib/polling';

export function DashboardPage() {
  const { t } = useTranslation();
  const clients = usePoll(Clients.list, 5_000);
  const consultants = usePoll(Consultants.list, 30_000);
  const license = usePoll(System.license, 60_000);

  const totalClients = clients.data?.length ?? 0;
  const onlineClients = clients.data?.filter((c) => c.tunnel_state === 'up').length ?? 0;
  const activeConsultants = consultants.data?.filter((c) => c.active).length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">{t('dashboard.title')}</h1>
      </div>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('dashboard.consultants_active')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{activeConsultants}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('dashboard.clients_online')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {onlineClients}
              <span className="text-base text-muted-foreground"> / {totalClients}</span>
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('dashboard.tunnels_total')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{totalClients}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('dashboard.license_status')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="truncate text-lg">{(license.data?.status as string) ?? '—'}</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
