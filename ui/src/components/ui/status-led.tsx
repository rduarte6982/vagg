import { type HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

export type LedState = 'on' | 'warn' | 'off' | 'error';

interface StatusLedProps extends HTMLAttributes<HTMLSpanElement> {
  state: LedState;
  label?: string;
}

/**
 * LED indicador estilo painel de roteador. Usado em listagem de túneis,
 * status de internet/health e ao lado de nomes de cliente.
 */
export function StatusLed({ state, label, className, ...rest }: StatusLedProps) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)} {...rest}>
      <span
        className={cn(
          'router-led',
          state === 'on' && 'router-led--on',
          state === 'warn' && 'router-led--warn',
          state === 'off' && 'router-led--off',
          state === 'error' && 'router-led--error',
        )}
        aria-hidden
      />
      {label && <span className="text-xs font-medium text-muted-foreground">{label}</span>}
    </span>
  );
}
