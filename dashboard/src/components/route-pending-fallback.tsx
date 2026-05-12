export function RoutePendingFallback() {
  return (
    <div className="flex h-full items-center justify-center bg-background/80">
      <div className="rounded-xl border bg-card px-4 py-3 text-sm text-muted-foreground shadow-sm">
        正在切换页面...
      </div>
    </div>
  )
}
