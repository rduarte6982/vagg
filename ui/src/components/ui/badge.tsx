import { cva, type VariantProps } from 'class-variance-authority';
import { type HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        // VAGG dark theme — todas variantes usam tinted bg + cor brand correspondente.
        default: 'bg-secondary text-foreground border border-border',
        secondary: 'bg-secondary text-muted-foreground border border-border',
        destructive: 'bg-[oklch(70%_0.18_25_/_0.14)] text-[oklch(78%_0.16_25)] border border-[oklch(70%_0.18_25_/_0.3)]',
        success: 'bg-[oklch(72%_0.16_160_/_0.12)] text-[oklch(72%_0.16_160)] border border-[oklch(72%_0.16_160_/_0.3)]',
        warning: 'bg-[oklch(78%_0.14_75_/_0.12)] text-[oklch(78%_0.14_75)] border border-[oklch(78%_0.14_75_/_0.3)]',
        info: 'bg-[oklch(72%_0.16_160_/_0.10)] text-[oklch(72%_0.16_160)] border border-[oklch(72%_0.16_160_/_0.25)]',
        outline: 'border border-border bg-popover text-muted-foreground',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };
