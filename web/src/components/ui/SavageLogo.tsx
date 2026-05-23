import { cn } from '@/lib/utils'

export function SavageLogo({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="Savage Analytics"
    >
      {/* Outer 4-pointed star — concave bezier sides */}
      <path
        d="M50 3 C53 26 74 47 97 50 C74 53 53 74 50 97 C47 74 26 53 3 50 C26 47 47 26 50 3 Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      {/* Inner rotated diamond */}
      <path d="M50 31 L69 50 L50 69 L31 50 Z" stroke="currentColor" strokeWidth="1.2" />
      {/* Spokes: inner diamond corners → outer tips */}
      <line x1="50" y1="3"  x2="50" y2="31" stroke="currentColor" strokeWidth="1" />
      <line x1="97" y1="50" x2="69" y2="50" stroke="currentColor" strokeWidth="1" />
      <line x1="50" y1="97" x2="50" y2="69" stroke="currentColor" strokeWidth="1" />
      <line x1="3"  y1="50" x2="31" y2="50" stroke="currentColor" strokeWidth="1" />
      {/* Center cross inside inner diamond */}
      <line x1="31" y1="50" x2="69" y2="50" stroke="currentColor" strokeWidth="0.6" opacity="0.45" />
      <line x1="50" y1="31" x2="50" y2="69" stroke="currentColor" strokeWidth="0.6" opacity="0.45" />
      {/* Facet lines — 2 per quadrant, from inner diamond to star-side midpoints */}
      <line x1="50" y1="31" x2="73" y2="27" stroke="currentColor" strokeWidth="0.7" opacity="0.65" />
      <line x1="69" y1="50" x2="73" y2="27" stroke="currentColor" strokeWidth="0.7" opacity="0.65" />
      <line x1="69" y1="50" x2="73" y2="73" stroke="currentColor" strokeWidth="0.7" opacity="0.65" />
      <line x1="50" y1="69" x2="73" y2="73" stroke="currentColor" strokeWidth="0.7" opacity="0.65" />
      <line x1="50" y1="69" x2="27" y2="73" stroke="currentColor" strokeWidth="0.7" opacity="0.65" />
      <line x1="31" y1="50" x2="27" y2="73" stroke="currentColor" strokeWidth="0.7" opacity="0.65" />
      <line x1="31" y1="50" x2="27" y2="27" stroke="currentColor" strokeWidth="0.7" opacity="0.65" />
      <line x1="50" y1="31" x2="27" y2="27" stroke="currentColor" strokeWidth="0.7" opacity="0.65" />
      {/* Center dot */}
      <circle cx="50" cy="50" r="3.5" fill="currentColor" />
    </svg>
  )
}

export function SavageWordmark({ className }: { className?: string }) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <SavageLogo size={18} className="text-cyan" />
      <div className="flex flex-col leading-none">
        <span className="text-[11px] font-semibold tracking-[0.22em] text-ink">SAVAGE</span>
        <span className="text-[8px] tracking-[0.18em] text-muted">ANALYTICS</span>
      </div>
    </div>
  )
}
