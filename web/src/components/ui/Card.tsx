import type { HTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  interactive?: boolean
}

export function Card({ className, interactive, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'glass p-6 transition-all duration-200',
        interactive &&
          'cursor-pointer hover:bg-surface-raised hover:shadow-[0_8px_32px_rgba(0,0,0,0.4)] hover:border-white/[0.16]',
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('mb-4 flex items-start justify-between gap-3', className)} {...props} />
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn('text-lg font-semibold tracking-tight text-ink', className)} {...props} />
}

export function CardLabel({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p
      className={cn('text-sm font-medium uppercase tracking-wide text-muted', className)}
      {...props}
    />
  )
}
