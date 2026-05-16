import { useCallback, useEffect, useMemo, useState } from 'react'
import { Eye, Loader2, RefreshCw, RotateCcw, Save, Search, SlidersHorizontal } from 'lucide-react'

import { CodeEditor } from '@/components/CodeEditor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/hooks/use-toast'
import {
  getDefaultPromptFile,
  getPromptCatalog,
  getPromptFile,
  resetPromptFile,
  updatePromptFile,
  type PromptCatalog,
  type PromptFileInfo,
} from '@/lib/prompt-api'
import { cn } from '@/lib/utils'

function formatFileSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export function PromptManagementPage() {
  const { toast } = useToast()
  const [catalog, setCatalog] = useState<PromptCatalog | null>(null)
  const [language, setLanguage] = useState('zh-CN')
  const [filename, setFilename] = useState('')
  const [content, setContent] = useState('')
  const [savedContent, setSavedContent] = useState('')
  const [loadingCatalog, setLoadingCatalog] = useState(true)
  const [loadingFile, setLoadingFile] = useState(false)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [loadingDefaultPrompt, setLoadingDefaultPrompt] = useState(false)
  const [defaultPromptOpen, setDefaultPromptOpen] = useState(false)
  const [defaultPromptContent, setDefaultPromptContent] = useState('')
  const [query, setQuery] = useState('')
  const [showAdvancedPrompts, setShowAdvancedPrompts] = useState(false)

  const hasUnsavedChanges = content !== savedContent

  const promptFiles = useMemo<PromptFileInfo[]>(() => {
    if (!catalog || !language) return []
    return catalog.files[language] ?? []
  }, [catalog, language])

  const visiblePromptFiles = useMemo<PromptFileInfo[]>(() => {
    return showAdvancedPrompts ? promptFiles : promptFiles.filter((file) => !file.advanced)
  }, [promptFiles, showAdvancedPrompts])

  const filteredFiles = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    if (!normalizedQuery) return visiblePromptFiles
    return visiblePromptFiles.filter((file) => {
      const searchableText = [
        file.name,
        file.display_name,
        file.description,
      ].join(' ').toLowerCase()
      return searchableText.includes(normalizedQuery)
    })
  }, [visiblePromptFiles, query])

  const selectedFile = promptFiles.find((file) => file.name === filename)
  const isCustomized = selectedFile?.customized ?? false
  useEffect(() => {
    if (!filename || showAdvancedPrompts) return
    const currentFile = promptFiles.find((file) => file.name === filename)
    if (!currentFile?.advanced) return
    setFilename(visiblePromptFiles[0]?.name ?? '')
  }, [filename, promptFiles, showAdvancedPrompts, visiblePromptFiles])

  const loadCatalog = useCallback(async () => {
    try {
      setLoadingCatalog(true)
      const result = await getPromptCatalog()
      if (!result.success) {
        toast({ title: '加载 Prompt 目录失败', description: result.error, variant: 'destructive' })
        return
      }

      setCatalog(result.data)
      const nextLanguage = language && result.data.languages.includes(language)
        ? language
        : result.data.languages.includes('zh-CN')
          ? 'zh-CN'
        : result.data.languages[0] ?? ''
      setLanguage(nextLanguage)

      const nextFiles = nextLanguage ? result.data.files[nextLanguage] ?? [] : []
      const nextBasicFiles = nextFiles.filter((file) => !file.advanced)
      setFilename((current) =>
        nextFiles.some((file) => file.name === current) ? current : nextBasicFiles[0]?.name ?? nextFiles[0]?.name ?? ''
      )
    } catch (error) {
      toast({
        title: '加载 Prompt 目录失败',
        description: (error as Error).message,
        variant: 'destructive',
      })
    } finally {
      setLoadingCatalog(false)
    }
  }, [language, toast])

  useEffect(() => {
    void loadCatalog()
  }, [loadCatalog])

  useEffect(() => {
    if (!language || !filename) {
      setContent('')
      setSavedContent('')
      return
    }

    let cancelled = false
    const loadFile = async () => {
      try {
        setLoadingFile(true)
        const result = await getPromptFile(language, filename)
        if (cancelled) return
        if (!result.success) {
          toast({ title: '读取 Prompt 失败', description: result.error, variant: 'destructive' })
          return
        }
        setContent(result.data.content)
        setSavedContent(result.data.content)
      } catch (error) {
        if (!cancelled) {
          toast({
            title: '读取 Prompt 失败',
            description: (error as Error).message,
            variant: 'destructive',
          })
        }
      } finally {
        if (!cancelled) {
          setLoadingFile(false)
        }
      }
    }

    void loadFile()
    return () => {
      cancelled = true
    }
  }, [filename, language, toast])

  const handleLanguageChange = (nextLanguage: string) => {
    setLanguage(nextLanguage)
    setQuery('')
    const nextFiles = catalog?.files[nextLanguage] ?? []
    const nextVisibleFiles = showAdvancedPrompts ? nextFiles : nextFiles.filter((file) => !file.advanced)
    setFilename(nextVisibleFiles[0]?.name ?? '')
  }

  const handleSave = async () => {
    if (!language || !filename) return

    try {
      setSaving(true)
      const result = await updatePromptFile(language, filename, content)
      if (!result.success) {
        toast({ title: '保存 Prompt 失败', description: result.error, variant: 'destructive' })
        return
      }

      setContent(result.data.content)
      setSavedContent(result.data.content)
      toast({ title: 'Prompt 已保存', description: `${language}/${filename}` })
      void loadCatalog()
    } catch (error) {
      toast({
        title: '保存 Prompt 失败',
        description: (error as Error).message,
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  const handleShowDefault = async () => {
    if (!language || !filename) return

    try {
      setLoadingDefaultPrompt(true)
      setDefaultPromptOpen(true)
      const result = await getDefaultPromptFile(language, filename)
      if (!result.success) {
        toast({ title: '读取默认 Prompt 失败', description: result.error, variant: 'destructive' })
        setDefaultPromptOpen(false)
        return
      }

      setDefaultPromptContent(result.data.content)
    } catch (error) {
      toast({
        title: '读取默认 Prompt 失败',
        description: (error as Error).message,
        variant: 'destructive',
      })
      setDefaultPromptOpen(false)
    } finally {
      setLoadingDefaultPrompt(false)
    }
  }

  const handleReset = async () => {
    if (!language || !filename || !isCustomized) return

    try {
      setResetting(true)
      const result = await resetPromptFile(language, filename)
      if (!result.success) {
        toast({ title: '恢复默认 Prompt 失败', description: result.error, variant: 'destructive' })
        return
      }

      setContent(result.data.content)
      setSavedContent(result.data.content)
      toast({ title: '已恢复默认 Prompt', description: `${language}/${filename}` })
      void loadCatalog()
    } catch (error) {
      toast({
        title: '恢复默认 Prompt 失败',
        description: (error as Error).message,
        variant: 'destructive',
      })
    } finally {
      setResetting(false)
    }
  }

  return (
    <div className="flex h-[calc(100vh-140px)] flex-col gap-4 p-4 sm:p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold sm:text-2xl md:text-3xl">Prompt 管理</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={language} onValueChange={handleLanguageChange} disabled={loadingCatalog}>
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="选择语言" />
            </SelectTrigger>
            <SelectContent>
              {(catalog?.languages ?? []).map((item) => (
                <SelectItem key={item} value={item}>{item}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            onClick={() => void loadCatalog()}
            disabled={loadingCatalog}
            title="刷新"
            aria-label="刷新"
          >
            <RefreshCw className={cn('h-4 w-4', loadingCatalog && 'animate-spin')} />
          </Button>
          <Button
            variant={showAdvancedPrompts ? 'default' : 'outline'}
            size="sm"
            onClick={() => setShowAdvancedPrompts((current) => !current)}
          >
            <SlidersHorizontal className="mr-2 h-4 w-4" />
            {showAdvancedPrompts ? '隐藏高级' : '显示高级'}
          </Button>
          <Button size="sm" onClick={handleSave} disabled={!hasUnsavedChanges || saving || loadingFile || !filename}>
            <Save className="mr-2 h-4 w-4" />
            {saving ? '保存中' : hasUnsavedChanges ? '保存' : '已保存'}
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <Card className="flex min-h-0 flex-col overflow-hidden">
          <CardHeader className="shrink-0 pb-3">
            <div className="flex items-center gap-2">
              <Badge variant="secondary" className="shrink-0">{filteredFiles.length}</Badge>
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="搜索"
                  className="pl-8"
                />
              </div>
            </div>
          </CardHeader>
          <Separator />
          <ScrollArea className="min-h-0 flex-1" scrollbars="vertical">
            <div className="space-y-1 p-2">
              {loadingCatalog ? (
                <div className="flex items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Thinking
                </div>
              ) : filteredFiles.length > 0 ? (
                filteredFiles.map((file) => (
                  <button
                    key={file.name}
                    type="button"
                    onClick={() => setFilename(file.name)}
                    className={cn(
                      'w-full rounded-md px-3 py-2 text-left text-sm transition-colors',
                      'hover:bg-accent hover:text-accent-foreground',
                      filename === file.name ? 'bg-accent text-accent-foreground' : 'text-muted-foreground',
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <div className="truncate font-medium" title={file.display_name || file.name}>
                        {file.display_name || file.name}
                      </div>
                      {file.advanced && <Badge variant="outline" className="shrink-0 text-[10px]">高级</Badge>}
                      {file.customized && <Badge variant="secondary" className="shrink-0 text-[10px]">自定义</Badge>}
                    </div>
                    <div className="mt-0.5 truncate text-xs text-muted-foreground">{file.name}</div>
                    {file.description && (
                      <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{file.description}</div>
                    )}
                  </button>
                ))
              ) : (
                <div className="p-6 text-center text-sm text-muted-foreground">没有可编辑的 Prompt 文件</div>
              )}
            </div>
          </ScrollArea>
        </Card>

        <Card className="min-h-0 overflow-hidden">
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-3">
            <div className="min-w-0">
              <CardTitle className="flex items-center gap-2 truncate text-sm">
                <span className="truncate">{selectedFile?.display_name || filename || '未选择文件'}</span>
                {selectedFile?.advanced && <Badge variant="outline" className="shrink-0">高级</Badge>}
                {isCustomized && <Badge variant="secondary" className="shrink-0">自定义</Badge>}
              </CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                {language}
                {selectedFile ? ` · ${formatFileSize(selectedFile.size)}` : ''}
                {hasUnsavedChanges ? ' · 有未保存修改' : ''}
              </p>
              {selectedFile?.description && (
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{selectedFile.description}</p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleReset}
                disabled={!isCustomized || resetting || loadingFile || !filename}
              >
                <RotateCcw className={cn('mr-2 h-4 w-4', resetting && 'animate-spin')} />
                恢复默认
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleShowDefault}
                disabled={loadingDefaultPrompt || loadingFile || !filename}
              >
                <Eye className={cn('mr-2 h-4 w-4', loadingDefaultPrompt && 'animate-pulse')} />
                查看默认
              </Button>
            </div>
          </CardHeader>
          <CardContent className="min-h-0 p-0">
            {loadingFile ? (
              <div className="flex h-[calc(100vh-290px)] items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Thinking
              </div>
            ) : (
              <CodeEditor
                value={content}
                onChange={setContent}
                language="text"
                height="calc(100vh - 290px)"
                minHeight="520px"
                placeholder="选择一个 Prompt 文件后开始编辑"
              />
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={defaultPromptOpen} onOpenChange={setDefaultPromptOpen}>
        <DialogContent className="max-w-[min(96vw,1100px)]">
          <DialogHeader>
            <DialogTitle>默认 Prompt</DialogTitle>
            <DialogDescription>
              {language}/{filename} 的内置模板，只读显示，不会修改或删除自定义内容。
            </DialogDescription>
          </DialogHeader>
          {loadingDefaultPrompt ? (
            <div className="flex h-[520px] items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Thinking
            </div>
          ) : (
            <CodeEditor
              value={defaultPromptContent}
              readOnly
              language="text"
              height="min(62vh, 620px)"
              minHeight="420px"
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
