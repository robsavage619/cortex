import type { ButtonHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

type Variant = 'primary' | 'glass' | 'ghost' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
}

const base =
  'inline-flex items-center justify-center gap-2 rounded-2xl px-5 py-2.5 text-sm font-semibold ' +
  'transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 ' +
  'active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50'

const variants: Record<Variant, string> = {
  primary:
    'accent-gradient text-white hover:shadow-[0_0_24px_rgba(34,211,238,0.25)]',
  glass:
    'bg-surface border border-hairline text-ink hover:bg-surface-raised hover:border-white/[0.16]',
  ghost: 'text-muted hover:text-ink',
  danger:
    'bg-down/15 border border-down/30 text-down hover:bg-down/25',
}

export function Button({ className, variant = 'glass', ...props }: ButtonProps) {
  return <button className={cn(base, variants[variant], className)} {...props} />
}
