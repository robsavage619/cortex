import { BarChart3, LayoutDashboard, ListChecks, PlusCircle } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { BANNER } from '@/lib/types'
import { cn } from '@/lib/utils'

const nav = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/review', label: 'Review queue', icon: ListChecks, end: false },
  { to: '/calibration', label: 'Calibration', icon: BarChart3, end: false },
  { to: '/new', label: 'New thesis', icon: PlusCircle, end: false },
]

export function Layout() {
  return (
    <div className="min-h-screen bg-bg text-ink">
      <div className="mx-auto flex max-w-[1280px] flex-col gap-6 px-4 py-6 md:flex-row md:px-8 md:py-8 lg:px-12">
        <aside className="md:w-60 md:shrink-0">
          <div className="mb-6 flex items-center gap-3">
            <div className="accent-gradient flex h-9 w-9 items-center justify-center rounded-2xl text-sm font-bold text-white">
              W
            </div>
            <div>
              <p className="font-semibold leading-tight">Wall Street Tracker</p>
              <p className="text-xs text-faint">Decision quality</p>
            </div>
          </div>
          <nav className="flex gap-2 overflow-x-auto md:flex-col md:gap-1">
            {nav.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 whitespace-nowrap rounded-xl px-3 py-2 text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-surface text-ink'
                      : 'text-muted hover:bg-surface hover:text-ink',
                  )
                }
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </nav>
        </aside>

        <main className="min-w-0 flex-1">
          <div className="mb-5 rounded-xl border border-hairline bg-surface px-4 py-2 text-xs text-muted">
            {BANNER}
          </div>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
