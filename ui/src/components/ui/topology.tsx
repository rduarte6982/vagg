import { Cloud, Server, Network, Building2, Cpu } from 'lucide-react';
import { cn } from '@/lib/utils';
import { StatusLed } from './status-led';

export interface TopologyClient {
  id: string;
  name: string;
  state: 'on' | 'warn' | 'off' | 'error';
  vpn_type?: string;
}

interface TopologyMapProps {
  clients: TopologyClient[];
  consultantsActive: number;
  hubLabel?: string;
  className?: string;
}

/**
 * Diagrama de topologia inspirado no "Network Map" do TP-Link Tether/Omada:
 * Internet → Aggregator (hub central) → clientes ao redor. As linhas
 * coloridas refletem o estado dos túneis em tempo real.
 */
export function TopologyMap({
  clients,
  consultantsActive,
  hubLabel = 'Aggregator',
  className,
}: TopologyMapProps) {
  const slice = clients.slice(0, 6);
  const hasMore = clients.length - slice.length;

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-md border bg-gradient-to-br from-white via-white to-secondary/40 p-6 shadow-card',
        className,
      )}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="router-section-title">Topologia</p>
          <h3 className="text-base font-semibold">Mapa da rede</h3>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="router-led router-led--on" /> ativo
          </span>
          <span className="flex items-center gap-1.5">
            <span className="router-led router-led--warn" /> negociando
          </span>
          <span className="flex items-center gap-1.5">
            <span className="router-led router-led--error" /> erro
          </span>
        </div>
      </div>

      <div className="mt-6 flex items-center justify-center gap-12">
        {/* Internet */}
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full border border-border bg-popover text-muted-foreground shadow-sm">
            <Cloud size={26} />
          </div>
          <span className="text-xs font-medium text-muted-foreground">Internet</span>
        </div>

        {/* Pipe */}
        <div className="relative h-1 w-16 rounded-full bg-gradient-to-r from-router-led-on/70 to-router-led-on" />

        {/* Hub */}
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="relative flex h-20 w-20 items-center justify-center rounded-full border-2 border-primary/30 bg-primary text-white shadow-pop">
            <Server size={32} />
            <span className="router-led router-led--on absolute -right-1 -top-1 h-3 w-3" />
          </div>
          <span className="text-sm font-semibold text-foreground">{hubLabel}</span>
          <span className="text-[11px] text-muted-foreground">
            {consultantsActive} consultor(es) online
          </span>
        </div>

        {/* Pipe */}
        <div className="relative h-1 w-16 rounded-full bg-gradient-to-r from-primary/60 to-primary/10" />

        {/* Clientes */}
        <div className="grid max-w-[18rem] grid-cols-3 gap-3">
          {slice.length === 0 && (
            <div className="col-span-3 flex h-24 items-center justify-center rounded-md border border-dashed border-border text-xs text-muted-foreground">
              Nenhum cliente cadastrado
            </div>
          )}
          {slice.map((c) => (
            <div
              key={c.id}
              className="group relative flex flex-col items-center gap-1.5 rounded-md border border-border bg-popover px-2 py-2 text-center shadow-sm transition-shadow hover:shadow-card"
              title={`${c.name} (${c.vpn_type ?? '—'})`}
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-secondary text-primary">
                {c.id.length % 2 === 0 ? <Building2 size={16} /> : <Network size={16} />}
              </div>
              <span className="line-clamp-1 text-[11px] font-medium text-foreground">
                {c.name}
              </span>
              <StatusLed state={c.state} />
            </div>
          ))}
          {hasMore > 0 && (
            <div className="col-span-3 flex items-center justify-center gap-2 rounded-md bg-secondary/60 px-2 py-1.5 text-[11px] font-medium text-primary">
              <Cpu size={12} />+{hasMore} cliente(s)
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
