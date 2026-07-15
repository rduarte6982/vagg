import { type ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface StatTileProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: 'default' | 'success' | 'warning' | 'danger';
  className?: string;
}

const toneAccent: Record<NonNullable<StatTileProps['tone']>, string> = {
  default: 'before:bg-primary',
  success: 'before:bg-router-led-on',
  warning: 'before:bg-router-led-warn',
  danger: 'before:bg-router-led-error',
};

/**
 * Stat tile estilo dashboard de roteador: borda lateral colorida (LED-like)
 * + número grande + ícone. Usado no Dashboard pra Consultores/Túneis/etc.
 */
export function StatTile({
  label,
  value,
  hint,
  icon,
  tone = 'default',
  className,
}: StatTileProps) {
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-md border bg-card px-5 py-4 shadow-card',
        'before:absolute before:left-0 before:top-0 before:h-full before:w-1',
        toneAccent[tone],
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </p>
          <p className="mt-2 text-2xl font-semibold leading-none text-foreground">{value}</p>
          {hint && <p className="mt-2 text-xs text-muted-foreground">{hint}</p>}
        </div>
        {icon && (
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-secondary text-primary">
            {icon}
          </div>
        )}
      </div>
    </div>
  );
}
