import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { CheckCircle2, Info, XCircle, AlertTriangle, X } from 'lucide-react';

export type ToastTone = 'success' | 'error' | 'info' | 'warning';

interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  detail?: string;
}

interface ToastCtx {
  push: (t: Omit<Toast, 'id'>) => void;
}

const ToastContext = createContext<ToastCtx | undefined>(undefined);

let nextId = 1;

// VAGG dark — tons usam o card escuro com borda colorida + ícone tinted.
const TONE_STYLE: Record<ToastTone, { bg: string; border: string; icon: ReactNode }> = {
  success: {
    bg: 'bg-card',
    border: 'border-[oklch(72%_0.16_160_/_0.5)]',
    icon: <CheckCircle2 size={16} className="text-[oklch(72%_0.16_160)]" />,
  },
  error: {
    bg: 'bg-card',
    border: 'border-[oklch(70%_0.18_25_/_0.5)]',
    icon: <XCircle size={16} className="text-[oklch(70%_0.18_25)]" />,
  },
  info: {
    bg: 'bg-card',
    border: 'border-[oklch(72%_0.16_160_/_0.4)]',
    icon: <Info size={16} className="text-[oklch(72%_0.16_160)]" />,
  },
  warning: {
    bg: 'bg-card',
    border: 'border-[oklch(78%_0.14_75_/_0.5)]',
    icon: <AlertTriangle size={16} className="text-[oklch(78%_0.14_75)]" />,
  },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);

  const push = useCallback((t: Omit<Toast, 'id'>) => {
    const id = nextId++;
    setItems((p) => [...p, { ...t, id }]);
    setTimeout(() => setItems((p) => p.filter((x) => x.id !== id)), 4500);
  }, []);

  const remove = (id: number) => setItems((p) => p.filter((x) => x.id !== id));

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
        {items.map((t) => {
          const s = TONE_STYLE[t.tone];
          return (
            <div
              key={t.id}
              className={`pointer-events-auto flex max-w-sm items-start gap-2 rounded-md border ${s.border} ${s.bg} px-3 py-2 shadow-lg`}
              role="status"
            >
              <span className="mt-0.5 shrink-0">{s.icon}</span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-foreground">{t.title}</p>
                {t.detail && <p className="mt-0.5 text-xs text-muted-foreground">{t.detail}</p>}
              </div>
              <button
                onClick={() => remove(t.id)}
                className="ml-1 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
                aria-label="fechar"
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastCtx {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // fallback — sem provider, vira no-op pra não quebrar testes
    return { push: () => {} };
  }
  return ctx;
}

// Hook conveniente: chama por tom
export function useToasts() {
  const { push } = useToast();
  return {
    success: (title: string, detail?: string) => push({ tone: 'success', title, detail }),
    error: (title: string, detail?: string) => push({ tone: 'error', title, detail }),
    info: (title: string, detail?: string) => push({ tone: 'info', title, detail }),
    warning: (title: string, detail?: string) => push({ tone: 'warning', title, detail }),
  };
}

// Re-export pra facilitar uso em testes
export { useEffect };
