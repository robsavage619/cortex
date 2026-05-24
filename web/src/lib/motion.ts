import type { Transition, Variants } from 'framer-motion'

export const spring: Transition = { type: 'spring', stiffness: 300, damping: 30 }
export const softEase: Transition = { duration: 0.4, ease: [0.16, 1, 0.3, 1] }

export const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05 } },
}

export const riseItem: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: spring },
}

export const fadeItem: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: softEase },
}
