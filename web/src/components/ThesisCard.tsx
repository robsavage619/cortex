import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'

import { StatusBadge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { ConvictionMeter } from '@/components/ui/ConvictionMeter'
import { Monogram } from '@/components/ui/Monogram'
import type { Thesis } from '@/lib/types'
import { daysUntil, fmtDate } from '@/lib/utils'

export function ThesisCard({ thesis }: { thesis: Thesis }) {
  const navigate = useNavigate()
  const days = daysUntil(thesis.review_date)
  const due = thesis.status === 'open' && days <= 0

  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <Card interactive onClick={() => navigate(`/thesis/${thesis.id}`)} className="h-full">
        <div className="flex items-start gap-3">
          <div className="flex -space-x-2">
            {thesis.tickers.slice(0, 3).map((t) => (
              <Monogram key={t} ticker={t} size="sm" className="ring-2 ring-bg" />
            ))}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="tabular text-sm font-semibold text-ink">
                {thesis.tickers.join(', ')}
              </span>
              <StatusBadge status={thesis.status} />
            </div>
            <p className="mt-0.5 text-xs text-faint">by {thesis.author}</p>
          </div>
        </div>

        <p className="mt-4 line-clamp-2 text-sm text-ink">{thesis.claim}</p>

        <div className="mt-4 flex items-center justify-between">
          <ConvictionMeter value={thesis.conviction} />
          <span className={`tabular text-xs ${due ? 'text-warn' : 'text-muted'}`}>
            {due ? 'Review due' : `Review ${fmtDate(thesis.review_date)}`}
          </span>
        </div>
      </Card>
    </motion.div>
  )
}
