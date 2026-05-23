import { motion } from 'framer-motion'
import type { ComponentProps, HTMLAttributes } from 'react'

import { spring } from '@/lib/motion'
import { cn } from '@/lib/utils'

type MotionDivProps = ComponentProps<typeof motion.div>

interface CardProps extends MotionDivProps {
  interactive?: boolean
}

export function Card({ className, interactive, ...props }: CardProps) {
  return (
    <motion.div
      whileHover={interactive ? { y: -2 } : undefined}
      transition={spring}
      className={cn(
        'glass p-5',
        interactive && 'cursor-pointer hover:glass-raised',
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
  return <h3 className={cn('text-base font-semibold tracking-tight text-ink', className)} {...props} />
}

export function CardLabel({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p
      className={cn(
        'text-[11px] font-medium uppercase tracking-[0.08em] text-faint',
        className,
      )}
      {...props}
    />
  )
}
