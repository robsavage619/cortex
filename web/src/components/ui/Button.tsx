import type { ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

type Variant = 'primary' | 'terminal' | 'ghost' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
}

const base =
  'inline-flex items-center justify-center gap-2 px-4 py-1.5 text-[11px] font-semibold ' +
  'tracking-[0.1em] uppercase transition-colors duration-150 ' +
  'focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan/50 ' +
  'disabled:cursor-not-allowed disabled:opacity-40 font-sans'

const variants: Record<Variant, string> = {
  primary:  'border border-cyan text-cyan hover:bg-cyan hover:text-bg',
  terminal: 'border border-border text-muted hover:border-border-bright hover:text-ink',
  ghost:    'text-muted hover:text-ink',
  danger:   'border border-down/40 text-down hover:bg-down/10',
}

export function Button({ className, variant = 'terminal', ...props }: ButtonProps) {
  return <button className={cn(base, variants[variant], className)} {...props} />
}
