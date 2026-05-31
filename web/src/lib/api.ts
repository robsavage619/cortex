import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import axios from 'axios'

import type {
  Calibration,
  CandidateResponse,
  CandidatesResponse,
  CaseResponse,
  CongressMemberProfile,
  CongressResponse,
  CongressStatsResponse,
  DailyCARPoint,
  Digest,
  DissentIn,
  FundsResponse,
  PriceHistory,
  Prior,
  PriorsIn,
  ReasoningResponse,
  RefreshStatus,
  ReviewIn,
  Thesis,
  ThesisIn,
  ThesisPatch,
  TickerContext,
  TickerResearch,
  VolScreenResponse,
} from './types'

// Dev: Vite proxies `/api/*` to the backend (stripping the prefix).
// Prod: the SPA is served by FastAPI on the same origin, where routes live at root.
export const http = axios.create({ baseURL: import.meta.env.DEV ? '/api' : '' })

const keys = {
  theses: ['theses'] as const,
  thesis: (id: string) => ['theses', id] as const,
  reviewQueue: ['review-queue'] as const,
  calibration: ['calibration'] as const,
  tickerContext: (ticker: string) => ['ticker-context', ticker] as const,
  history: (ticker: string, period: string) => ['history', ticker, period] as const,
  digest: ['digest'] as const,
  candidates: ['candidates'] as const,
  volatilityScreen: ['volatility-screen'] as const,
  candidate: (ticker: string) => ['candidate', ticker] as const,
  case: (ticker: string) => ['case', ticker] as const,
  tickerResearch: (ticker: string) => ['ticker-research', ticker] as const,
  congress: (ticker: string | null, days: number) => ['congress', ticker, days] as const,
  congressStats: (days: number) => ['congress-stats', days] as const,
  funds: (ticker: string | null) => ['funds', ticker] as const,
  refreshStatus: ['refresh-status'] as const,
  carSeries: (signal: string) => ['car-series', signal] as const,
}

export function useTheses(params?: { author?: string; status?: string }) {
  return useQuery({
    queryKey: [...keys.theses, params ?? {}],
    queryFn: async () => {
      const { data } = await http.get<{ theses: Thesis[] }>('/theses', { params })
      return data.theses
    },
  })
}

export function useThesis(id: string) {
  return useQuery({
    queryKey: keys.thesis(id),
    queryFn: async () => {
      const { data } = await http.get<{ thesis: Thesis }>(`/theses/${id}`)
      return data.thesis
    },
  })
}

export function useReviewQueue() {
  return useQuery({
    queryKey: keys.reviewQueue,
    queryFn: async () => {
      const { data } = await http.get<{ due: Thesis[] }>('/review-queue')
      return data.due
    },
  })
}

export function useCalibration() {
  return useQuery({
    queryKey: keys.calibration,
    queryFn: async () => {
      const { data } = await http.get<Calibration>('/calibration')
      return data
    },
  })
}

export function useTickerContext(ticker: string | null) {
  return useQuery({
    queryKey: keys.tickerContext(ticker ?? ''),
    enabled: Boolean(ticker),
    staleTime: 60_000,
    queryFn: async () => {
      const { data } = await http.get<TickerContext>(`/context/${ticker}`)
      return data
    },
  })
}

export function useHistory(ticker: string | null, period = '6mo') {
  return useQuery({
    queryKey: keys.history(ticker ?? '', period),
    enabled: Boolean(ticker),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data } = await http.get<PriceHistory>(`/context/${ticker}/history`, {
        params: { period },
      })
      return data.bars
    },
  })
}

export function useCreateThesis() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: ThesisIn) => {
      const { data } = await http.post<{ thesis: Thesis }>('/theses', body)
      return data.thesis
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.theses })
      void qc.invalidateQueries({ queryKey: keys.reviewQueue })
    },
  })
}

export function usePatchThesis(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: ThesisPatch) => {
      const { data } = await http.patch<{ thesis: Thesis }>(`/theses/${id}`, body)
      return data.thesis
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.thesis(id) })
      void qc.invalidateQueries({ queryKey: keys.theses })
    },
  })
}

export function useRecordReview(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: ReviewIn) => {
      const { data } = await http.post<{ status: string }>(`/theses/${id}/review`, body)
      return data
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.thesis(id) })
      void qc.invalidateQueries({ queryKey: keys.theses })
      void qc.invalidateQueries({ queryKey: keys.reviewQueue })
      void qc.invalidateQueries({ queryKey: keys.calibration })
    },
  })
}

export function useActivate(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await http.post<{ thesis: Thesis }>(`/theses/${id}/activate`)
      return data.thesis
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.thesis(id) })
      void qc.invalidateQueries({ queryKey: keys.theses })
    },
  })
}

export function useAddDissent(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: DissentIn) => {
      const { data } = await http.post<{ dissent: unknown }>(`/theses/${id}/dissents`, body)
      return data.dissent
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.thesis(id) })
    },
  })
}

export function useDigest() {
  return useQuery({
    queryKey: keys.digest,
    queryFn: async () => {
      const { data } = await http.get<Digest>('/digest')
      return data
    },
  })
}

export function useCandidates() {
  return useQuery({
    queryKey: keys.candidates,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data } = await http.get<CandidatesResponse>('/candidates')
      return data
    },
  })
}

export function useVolatilityScreen() {
  return useQuery({
    queryKey: keys.volatilityScreen,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data } = await http.get<VolScreenResponse>('/screen/volatility')
      return data
    },
  })
}

export function useCandidate(ticker: string | null) {
  return useQuery({
    queryKey: keys.candidate(ticker ?? ''),
    enabled: Boolean(ticker),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data } = await http.get<CandidateResponse>(`/candidates/${ticker}`)
      return data.candidate
    },
  })
}

export function useCase(ticker: string | null) {
  return useQuery({
    queryKey: keys.case(ticker ?? ''),
    enabled: Boolean(ticker),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data } = await http.get<CaseResponse>(`/candidates/${ticker}/case`)
      return data.case
    },
  })
}

export function useTickerResearch(ticker: string | null) {
  return useQuery({
    queryKey: keys.tickerResearch(ticker ?? ''),
    enabled: Boolean(ticker),
    staleTime: 10 * 60_000,
    queryFn: async () => {
      const { data } = await http.get<TickerResearch>(`/research/ticker/${ticker}`)
      return data
    },
  })
}

export function useCarSeries(signal: string) {
  return useQuery({
    queryKey: keys.carSeries(signal),
    staleTime: 24 * 60 * 60 * 1000,
    queryFn: async () => {
      const { data } = await http.get<{ series: DailyCARPoint[] }>(
        `/event-study/${signal}/car-series`,
      )
      return data.series
    },
  })
}

export function useCongress(ticker: string | null = null, days = 120) {
  return useQuery({
    queryKey: keys.congress(ticker, days),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data } = await http.get<CongressResponse>('/congress', {
        params: { ticker: ticker ?? undefined, days },
      })
      return data
    },
  })
}

export function useCongressStats(days = 365) {
  return useQuery({
    queryKey: keys.congressStats(days),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data } = await http.get<CongressStatsResponse>('/congress/stats', {
        params: { days },
      })
      return data
    },
  })
}

export function useCongressMember(name: string | null, days = 730) {
  return useQuery({
    queryKey: ['congress-member', name, days],
    enabled: !!name,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data } = await http.get<CongressMemberProfile>('/congress/member', {
        params: { name, days },
      })
      return data
    },
  })
}

export function useFunds(ticker: string | null = null) {
  return useQuery({
    queryKey: keys.funds(ticker),
    staleTime: 10 * 60_000,
    queryFn: async () => {
      const { data } = await http.get<FundsResponse>('/funds', {
        params: { ticker: ticker ?? undefined, actions: 'NEW,ADD', limit: 60 },
      })
      return data
    },
  })
}

export function useRefresh() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await http.post<RefreshStatus>('/refresh')
      return data
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.refreshStatus })
    },
  })
}

export function useRefreshStatus(enabled: boolean) {
  return useQuery({
    queryKey: keys.refreshStatus,
    enabled,
    refetchInterval: q => (!q.state.data || q.state.data.running ? 2000 : false),
    queryFn: async () => {
      const { data } = await http.get<RefreshStatus>('/refresh/status')
      return data
    },
  })
}

export function usePriors() {
  return useMutation({
    mutationFn: async (body: PriorsIn) => {
      const { data } = await http.post<{ priors: Prior[] }>('/research/priors', body)
      return data.priors
    },
  })
}

export function useGenerateReasoning() {
  return useMutation({
    mutationFn: async (ticker: string) => {
      const { data } = await http.post<ReasoningResponse>(`/context/${ticker}/reason`)
      return data.reasoning
    },
  })
}

async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // fall through to execCommand fallback
    }
  }
  const el = document.createElement('textarea')
  el.value = text
  el.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0'
  document.body.appendChild(el)
  el.focus()
  el.select()
  document.execCommand('copy')
  document.body.removeChild(el)
}

export function useCopyPrompt() {
  return useMutation({
    mutationFn: async (ticker: string) => {
      const { data } = await http.get<{ prompt: string }>(`/context/${ticker}/prompt`)
      await copyToClipboard(data.prompt)
      return data.prompt
    },
  })
}
