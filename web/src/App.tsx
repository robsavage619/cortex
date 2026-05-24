import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { Layout } from '@/components/Layout'
import { AriSpecial } from '@/views/AriSpecial'
import { Calibration } from '@/views/Calibration'
import { Congress } from '@/views/Congress'
import { Dashboard } from '@/views/Dashboard'
import { NewThesis } from '@/views/NewThesis'
import { ReviewQueue } from '@/views/ReviewQueue'
import { ThesisDetail } from '@/views/ThesisDetail'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="thesis/:id" element={<ThesisDetail />} />
            <Route path="new" element={<NewThesis />} />
            <Route path="ari-special" element={<AriSpecial />} />
            <Route path="congress" element={<Congress />} />
            <Route path="calibration" element={<Calibration />} />
            <Route path="review" element={<ReviewQueue />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
