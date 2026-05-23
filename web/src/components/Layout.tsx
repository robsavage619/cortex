import { BarChart3, LayoutDashboard, ListChecks, PlusCircle } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { cn } from '@/lib/utils'

const nav = [
  { to: '/',            label: 'DASHBOARD',  icon: LayoutDashboard, end: true  },
  { to: '/review',      label: 'REVIEW',     icon: ListChecks,      end: false },
  { to: '/calibration', label: 'CALIBRATE',  icon: BarChart3,       end: false },
  { to: '/new',         label: 'NEW THESIS', icon: PlusCircle,      end: false },
]

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col bg-bg font-mono text-ink">

      {/* ── Top bar ──────────────────────────────────────────── */}
      <header className="flex h-10 shrink-0 items-center border-b border-border bg-bg-panel">
        {/* Brand */}
        <div className="flex h-full items-center gap-2 border-r border-border px-4">
          <span className="text-[10px] font-semibold tracking-[0.2em] text-cyan">WST</span>
          <span className="text-[10px] tracking-widest text-muted">DECISION SYSTEM</span>
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
                    ? 'border-b border-b-cyan bg-bg-selected text-cyan'
                    : 'text-muted hover:bg-bg-hover hover:text-ink',
                )
              }
            >
              <Icon className="h-3 w-3" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Right: disclaimer */}
        <div className="ml-auto flex items-center px-4">
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
