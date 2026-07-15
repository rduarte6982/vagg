import { type ReactNode } from 'react';

interface TooltipProps {
  label: string;
  children: ReactNode;
  side?: 'top' | 'bottom';
}

/**
 * Tooltip CSS-only e rápido. Sem dependência de Radix nem state — usa
 * um span absolutamente posicionado dentro de um wrapper `group`. Aparece
 * imediatamente no hover, some no mouseleave. Sufficient pra ações de
 * tabela onde o user já sabe o que cada ícone faz; o tooltip é confirmação.
 */
export function Tooltip({ label, children, side = 'top' }: TooltipProps) {
  const pos = side === 'top' ? 'bottom-full mb-1' : 'top-full mt-1';
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        className={`pointer-events-none absolute left-1/2 -translate-x-1/2 ${pos} z-50 whitespace-nowrap rounded-md bg-slate-900 px-2 py-1 text-[11px] font-medium text-white opacity-0 shadow-md transition-opacity duration-100 group-hover:opacity-100`}
        role="tooltip"
      >
        {label}
      </span>
    </span>
  );
}
