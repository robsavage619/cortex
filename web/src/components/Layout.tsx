import { Activity, BarChart3, Landmark, LayoutDashboard, ListChecks, PlusCircle, Sparkles } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { HeaderTicker } from '@/components/ui/HeaderTicker'
import { useReviewQueue } from '@/lib/api'
import { usePlainMode } from '@/lib/plainMode'
import { cn } from '@/lib/utils'

const nav = [
  { to: '/',            label: 'DASHBOARD',  icon: LayoutDashboard, end: true  },
  { to: '/review',      label: 'REVIEW',     icon: ListChecks,      end: false },
  { to: '/swing', label: 'SWING', icon: Activity,       end: false },
  { to: '/congress',    label: 'CONGRESS',   icon: Landmark,        end: false },
  { to: '/calibration', label: 'CALIBRATE',  icon: BarChart3,       end: false },
  { to: '/new',         label: 'NEW THESIS', icon: PlusCircle,      end: false },
]

export function Layout() {
  const { data: due } = useReviewQueue()
  const dueCount = due?.length ?? 0
  const { plain, toggle } = usePlainMode()

  return (
    <div className="flex h-screen flex-col bg-bg font-mono text-ink">

      {/* ── Top bar ──────────────────────────────────────────── */}
      <header className="flex h-11 shrink-0 items-center border-b border-border bg-bg-panel">
        {/* Brand */}
        <div className="flex h-full items-center border-r border-border px-5 pr-6">
          <img
            src="/cortex-logo.png?v=3"
            alt="CORTEX"
            className="h-7 w-auto"
            style={{
              filter:
                'drop-shadow(0 0 4px rgba(34,211,238,0.7)) drop-shadow(0 0 12px rgba(34,211,238,0.35))',
            }}
          />
        </div>

        {/* Nav tabs */}
        <nav className="flex h-full items-stretch">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex h-full items-center gap-1.5 border-r border-border px-4 text-[11px] font-semibold tracking-[0.12em] transition-colors',
                  isActive
                    ? 'border-b-2 border-b-cyan bg-bg-selected text-cyan'
                    : 'text-muted hover:bg-bg-hover hover:text-ink',
                )
              }
            >
              <Icon className="h-3 w-3" />
              {label}
              {to === '/review' && dueCount > 0 && (
                <span className="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-warn px-1 text-[9px] font-bold leading-none text-bg">
                  {dueCount}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Live portfolio ticker */}
        <HeaderTicker />

        {/* Right: plain-English toggle + disclaimer */}
        <div className="flex items-center gap-3 px-4">
          <button
            onClick={toggle}
            title="Plain English — swap quant jargon (z-scores, factor codes) for plain language"
            className={cn(
              'flex items-center gap-1.5 rounded-sm border px-2 py-1 text-[10px] font-semibold tracking-wide transition-colors',
              plain
                ? 'border-cyan bg-cyan/10 text-cyan'
                : 'border-border text-muted hover:border-cyan/40 hover:text-ink',
            )}
          >
            <Sparkles className="h-3 w-3" />
            PLAIN
          </button>
          <span className="text-[10px] tracking-wide text-faint">
            NOT FINANCIAL ADVICE
          </span>
        </div>
      </header>

      {/* ── Content ──────────────────────────────────────────── */}
      <main className="flex min-h-0 flex-1 flex-col">
        <Outlet />
      </main>

    </div>
  )
}
