import { type ReactNode } from 'react';
import { ChevronRight, Home } from 'lucide-react';
import { Link } from 'react-router-dom';

interface PageHeaderProps {
  breadcrumb?: { label: string; to?: string }[];
  title: string;
  description?: string;
  actions?: ReactNode;
}

/**
 * Header de página estilo router admin: breadcrumb + título grande +
 * área para ações do lado direito. Substitui o "h1 + flex justify-between"
 * que era repetido em todas as páginas.
 */
export function PageHeader({ breadcrumb, title, description, actions }: PageHeaderProps) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {breadcrumb && breadcrumb.length > 0 && (
          <nav className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
            <Home size={12} className="text-muted-foreground/70" />
            {breadcrumb.map((b, i) => (
              <span key={i} className="flex items-center gap-1">
                <ChevronRight size={11} className="text-muted-foreground/60" />
                {b.to ? (
                  <Link to={b.to} className="hover:text-primary">
                    {b.label}
                  </Link>
                ) : (
                  <span>{b.label}</span>
                )}
              </span>
            ))}
          </nav>
        )}
        <h1 className="text-xl font-semibold leading-tight text-foreground">{title}</h1>
        {description && (
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
