import { animate, useReducedMotion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'

/**
 * Counts up to `value` once on mount. On later value changes it tweens
 * (no re-count from zero — that's nauseating in a tool used repeatedly).
 * Honors prefers-reduced-motion.
 */
export function AnimatedNumber({
  value,
  format,
  className,
}: {
  value: number
  format?: (n: number) => string
  className?: string
}) {
  const reduce = useReducedMotion()
  const [display, setDisplay] = useState(reduce ? value : 0)
  const prev = useRef(reduce ? value : 0)

  useEffect(() => {
    if (reduce) {
      setDisplay(value)
      prev.current = value
      return
    }
    const controls = animate(prev.current, value, {
      duration: 0.6,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setDisplay(v),
    })
    prev.current = value
    return () => controls.stop()
  }, [value, reduce])

  return <span className={className}>{format ? format(display) : Math.round(display)}</span>
}
