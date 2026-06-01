import { createContext, useCallback, useContext, useState } from 'react'

// App-wide "Plain English" toggle. When on, the UI swaps quant jargon (factor
// codes, z-scores) for plain language. Persisted so the choice sticks.

const LS_KEY = 'cortex:plainMode'

interface PlainModeCtx {
  plain: boolean
  toggle: () => void
}

const Ctx = createContext<PlainModeCtx>({ plain: false, toggle: () => {} })

export function PlainModeProvider({ children }: { children: React.ReactNode }) {
  const [plain, setPlain] = useState<boolean>(
    () => localStorage.getItem(LS_KEY) === '1',
  )
  const toggle = useCallback(() => {
    setPlain(prev => {
      const next = !prev
      localStorage.setItem(LS_KEY, next ? '1' : '0')
      return next
    })
  }, [])
  return <Ctx.Provider value={{ plain, toggle }}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components -- colocated hook for the context
export function usePlainMode(): PlainModeCtx {
  return useContext(Ctx)
}
