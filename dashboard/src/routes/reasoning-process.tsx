import { useEffect, useState } from 'react'
import {
  Clock,
  Code2,
  Copy,
  FileCode2,
  FileText,
  RefreshCw,
  Search,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  getReasoningPromptFile,
  getReasoningPromptHtmlUrl,
  listReasoningPromptFiles,
  type ReasoningPromptFile,
} from '@/lib/reasoning-process-api'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 50
const AUTO_SESSION = 'auto'

function formatTime(timestamp: number | null, modifiedAt: number): string {
  const value = timestamp ? timestamp : modifiedAt * 1000
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export function ReasoningProcessPage() {
  const { toast } = useToast()
  const [items, setItems] = useState<ReasoningPromptFile[]>([])
  const [stages, setStages] = useState<string[]>([])
  const [sessions, setSessions] = useState<string[]>([])
  const [stage, setStage] = useState('planner')
  const [session, setSession] = useState(AUTO_SESSION)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [refreshKey, setRefreshKey] = useState(0)
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState<ReasoningPromptFile | null>(null)
  const [textContent, setTextContent] = useState('')
  const [activePreview, setActivePreview] = useState<'text' | 'html'>('text')
  const [htmlPreviewUrl, setHtmlPreviewUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [contentLoading, setContentLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  useEffect(() => {
    let ignore = false

    async function loadFiles() {
      setLoading(true)
      setError(null)
      try {
        const data = await listReasoningPromptFiles({
          stage,
          session,
          search,
          page,
          pageSize: PAGE_SIZE,
        })
        if (ignore) return
        setItems(data.items)
        setStages(data.stages)
        setSessions(data.sessions)
        if (data.selected_session && data.selected_session !== session) {
          setSession(data.selected_session)
        }
        setTotal(data.total)
        setSelected((current) => {
          if (
            current &&
            data.items.some(
              (item) =>
                item.stem === current.stem &&
                item.stage === current.stage &&
                item.session_id === current.session_id
            )
          ) {
            return current
          }
          return data.items[0] ?? null
        })
      } catch (err) {
        if (!ignore) setError(err instanceof Error ? err.message : '加载推理过程失败')
      } finally {
        if (!ignore) setLoading(false)
      }
    }

    loadFiles()
    return () => {
      ignore = true
    }
  }, [page, refreshKey, search, session, stage])

  useEffect(() => {
    let ignore = false

    async function loadContent() {
      if (!selected?.text_path) {
        setTextContent('')
        return
      }

      setContentLoading(true)
      try {
        const data = await getReasoningPromptFile(selected.text_path)
        if (!ignore) setTextContent(data.content)
      } catch (err) {
        if (!ignore) {
          setTextContent(err instanceof Error ? err.message : '读取文本失败')
        }
      } finally {
        if (!ignore) setContentLoading(false)
      }
    }

    async function loadHtmlPreviewUrl() {
      if (!selected?.html_path) {
        setHtmlPreviewUrl('')
        return
      }
      const url = await getReasoningPromptHtmlUrl(selected.html_path)
      if (!ignore) setHtmlPreviewUrl(url)
    }

    if (selected?.html_path && !selected.text_path) {
      setActivePreview('html')
    } else {
      setActivePreview('text')
    }
    loadContent()
    loadHtmlPreviewUrl()
    return () => {
      ignore = true
    }
  }, [selected])

  function resetToFirstPage(nextAction: () => void) {
    nextAction()
    setPage(1)
  }

  async function handleCopyPrompt() {
    if (!textContent || contentLoading) {
      toast({
        title: '暂无可复制内容',
        description: '请先选择一条包含 txt 的 prompt 记录',
        variant: 'destructive',
      })
      return
    }

    try {
      await navigator.clipboard.writeText(textContent)
      toast({
        title: '已复制完整 Prompt',
        description: selected ? `${selected.stage}/${selected.session_id}/${selected.stem}` : undefined,
      })
    } catch (err) {
      toast({
        title: '复制失败',
        description: err instanceof Error ? err.message : '请手动选择文本复制',
        variant: 'destructive',
      })
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3 lg:p-4">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-normal text-foreground">推理过程</h1>
          <p className="text-sm text-muted-foreground">浏览 logs/maisaka_prompt 下的 prompt 记录</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setRefreshKey((current) => current + 1)}
          disabled={loading}
        >
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          刷新
        </Button>
      </div>

      <div className="grid flex-shrink-0 grid-cols-1 gap-2 md:grid-cols-[180px_240px_1fr]">
        <Select
          value={stage}
          onValueChange={(value) =>
            resetToFirstPage(() => {
              setStage(value)
              setSession(AUTO_SESSION)
              setSelected(null)
            })
          }
        >
          <SelectTrigger>
            <SelectValue placeholder="阶段" />
          </SelectTrigger>
          <SelectContent>
            {!stages.includes(stage) && (
              <SelectItem value={stage}>
                {stage}
              </SelectItem>
            )}
            {stages.map((item) => (
              <SelectItem key={item} value={item}>
                {item}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={session}
          onValueChange={(value) => resetToFirstPage(() => setSession(value))}
          disabled={sessions.length === 0 && loading}
        >
          <SelectTrigger>
            <SelectValue placeholder="会话" />
          </SelectTrigger>
          <SelectContent>
            {session === AUTO_SESSION && (
              <SelectItem value={AUTO_SESSION}>自动选择最近会话</SelectItem>
            )}
            {sessions.map((item) => (
              <SelectItem key={item} value={item}>
                {item}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => resetToFirstPage(() => setSearch(event.target.value))}
            className="pl-9"
            placeholder="搜索阶段、会话或文件名"
          />
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[360px_1fr]">
        <div className="flex min-h-0 flex-col overflow-hidden rounded-md border bg-background">
          <div className="flex h-11 flex-shrink-0 items-center justify-between border-b px-3 text-sm text-muted-foreground">
            <span>{total} 条记录</span>
            <span>
              第 {page} / {totalPages} 页
            </span>
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-1 p-2">
              {items.map((item) => {
                const active = selected?.stage === item.stage && selected?.session_id === item.session_id && selected?.stem === item.stem
                return (
                  <button
                    key={`${item.stage}/${item.session_id}/${item.stem}`}
                    type="button"
                    onClick={() => setSelected(item)}
                    className={cn(
                      'flex w-full flex-col gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors',
                      active
                        ? 'border-primary bg-primary/10 text-foreground'
                        : 'border-transparent hover:border-border hover:bg-muted/60'
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <Badge variant="secondary" className="max-w-[150px] truncate">
                        {item.stage}
                      </Badge>
                      <span className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Clock className="h-3.5 w-3.5" />
                        {formatTime(item.timestamp, item.modified_at)}
                      </span>
                    </div>
                    <div className="truncate font-medium">{item.session_id}</div>
                    <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span className="truncate">{item.stem}</span>
                      <span className="shrink-0">{formatSize(item.size)}</span>
                    </div>
                  </button>
                )
              })}
              {!loading && items.length === 0 && (
                <div className="px-3 py-10 text-center text-sm text-muted-foreground">
                  没有找到推理过程记录
                </div>
              )}
            </div>
          </ScrollArea>
          <div className="flex h-12 flex-shrink-0 items-center justify-between border-t px-3">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || loading}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              上一页
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
            >
              下一页
            </Button>
          </div>
        </div>

        <div className="flex min-h-0 flex-col overflow-hidden rounded-md border bg-background">
          <div className="flex min-h-14 flex-shrink-0 flex-col gap-1 border-b px-4 py-3 md:flex-row md:items-center md:justify-between">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">
                {selected ? `${selected.stage}/${selected.session_id}/${selected.stem}` : '未选择记录'}
              </div>
              <div className="text-xs text-muted-foreground">
                {selected ? `${formatSize(selected.size)} · ${formatTime(selected.timestamp, selected.modified_at)}` : '从左侧列表选择一条记录'}
              </div>
            </div>
            {selected && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1.5"
                  onClick={handleCopyPrompt}
                  disabled={!selected.text_path || contentLoading || !textContent}
                  title="复制完整 Prompt"
                >
                  <Copy className="h-3.5 w-3.5" />
                  复制
                </Button>
                {selected.text_path && (
                  <span className="inline-flex items-center gap-1">
                    <FileText className="h-3.5 w-3.5" />
                    txt
                  </span>
                )}
                {selected.html_path && (
                  <span className="inline-flex items-center gap-1">
                    <FileCode2 className="h-3.5 w-3.5" />
                    html
                  </span>
                )}
              </div>
            )}
          </div>

          <Tabs
            value={activePreview}
            onValueChange={(value) => setActivePreview(value as 'text' | 'html')}
            className="flex min-h-0 flex-1 flex-col"
          >
            <div className="flex flex-shrink-0 border-b px-3 py-2">
              <TabsList>
                <TabsTrigger value="text" disabled={!selected?.text_path}>
                  <FileText className="mr-1 h-4 w-4" />
                  文本
                </TabsTrigger>
                <TabsTrigger value="html" disabled={!selected?.html_path}>
                  <Code2 className="mr-1 h-4 w-4" />
                  HTML
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="text" className="m-0 min-h-0 flex-1 overflow-hidden">
              <ScrollArea className="h-full">
                <pre className="min-h-full whitespace-pre-wrap break-words p-4 font-mono text-xs leading-5 text-foreground">
                  {contentLoading ? '正在读取...' : textContent || '没有文本内容'}
                </pre>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="html" className="m-0 min-h-0 flex-1 overflow-hidden">
              {selected?.html_path && htmlPreviewUrl ? (
                <iframe
                  title="推理过程 HTML 预览"
                  src={htmlPreviewUrl}
                  sandbox=""
                  className="h-full w-full border-0 bg-white"
                />
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  没有 HTML 预览
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  )
}
