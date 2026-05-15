import { useEffect, useState } from 'react'

export function RoutePendingFallback() {
  const [dotCount, setDotCount] = useState(6)

  useEffect(() => {
    const timer = window.setInterval(() => {
      setDotCount((current) => (current >= 6 ? 2 : current + 1))
    }, 450)

    return () => window.clearInterval(timer)
  }, [])

  return (
    <div className="flex h-full items-center justify-center bg-background/80">
      <div className="min-w-[10rem] rounded-xl border bg-card px-5 py-3.5 text-base font-medium text-muted-foreground shadow-sm">
        Thinking{'.'.repeat(dotCount)}
      </div>
    </div>
  )
}
