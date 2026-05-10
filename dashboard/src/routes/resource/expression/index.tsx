import { ClipboardCheck, Download, MessageSquare, Plus, Search, Trash2, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'

import { Button } from '@/components/ui/button'
import { ExpressionReviewer } from '@/components/expression-reviewer'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/hooks/use-toast'

import {
  batchDeleteExpressions,
  clearExpressions,
  deleteExpression,
  exportExpressions,
  getChatList,
  getExpressionDetail,
  getExpressionGroups,
  getExpressionList,
  getExpressionStats,
  getReviewStats,
  importExpressions,
} from '@/lib/expression-api'

import {
  BatchDeleteConfirmDialog,
  ClearChatExpressionsConfirmDialog,
  DeleteConfirmDialog,
  ExpressionCreateDialog,
  ExpressionDetailDialog,
  ExpressionEditDialog,
  LegacyExpressionImportDialog,
} from './ExpressionDialogs'
import { ExpressionList } from './ExpressionList'

import type { ChatInfo, Expression, ExpressionExportItem, ExpressionGroupInfo } from '@/types/expression'
import type { StatsData } from './types'

type IndicatorStatus = 'on' | 'off' | 'mixed'

interface ExpressionLearningScopeStatus {
  label: string
  useExpression: IndicatorStatus
  enableLearning: IndicatorStatus
}

/**
 * 表达方式管理主页面
 */
export function ExpressionManagementPage() {
  const [expressions, setExpressions] = useState<Expression[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [browseMode, setBrowseMode] = useState<'chat' | 'group' | 'all'>('chat')
  const [showLegacyExpressions, setShowLegacyExpressions] = useState(false)
  const [selectedChatId, setSelectedChatId] = useState('')
  const [selectedGroupIndex, setSelectedGroupIndex] = useState<number | null>(null)
  const [selectedExpression, setSelectedExpression] = useState<Expression | null>(null)
  const [isDetailDialogOpen, setIsDetailDialogOpen] = useState(false)
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false)
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [isLegacyImportOpen, setIsLegacyImportOpen] = useState(false)
  const [deleteConfirmExpression, setDeleteConfirmExpression] = useState<Expression | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [isBatchDeleteDialogOpen, setIsBatchDeleteDialogOpen] = useState(false)
  const [isClearConfirmOpen, setIsClearConfirmOpen] = useState(false)
  const [stats, setStats] = useState<StatsData>({ total: 0, recent_7days: 0, chat_count: 0, top_chats: {} })
  const [chatList, setChatList] = useState<ChatInfo[]>([])
  const [expressionGroups, setExpressionGroups] = useState<ExpressionGroupInfo[]>([])
  const [chatNameMap, setChatNameMap] = useState<Map<string, string>>(new Map())
  const [isReviewerOpen, setIsReviewerOpen] = useState(false)
  const [uncheckedCount, setUncheckedCount] = useState(0)
  const { toast } = useToast()
  const importInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (browseMode !== 'chat') return
    if (!selectedChatId && chatList.length > 0) {
      setSelectedChatId(chatList[0].chat_id)
    }
    if (selectedChatId && chatList.length > 0 && !chatList.some((chat) => chat.chat_id === selectedChatId)) {
      setSelectedChatId(chatList[0].chat_id)
    }
  }, [browseMode, chatList, selectedChatId])

  // 加载表达方式列表
  const loadExpressions = async () => {
    try {
      setLoading(true)
      const selectedGroup = browseMode === 'group'
        ? expressionGroups.find((group) => group.index === selectedGroupIndex)
        : undefined
      if (selectedGroup && !selectedGroup.is_global && selectedGroup.chat_ids.length === 0) {
        setExpressions([])
        setTotal(0)
        return
      }
      const result = await getExpressionList({
        page,
        page_size: pageSize,
        search: search || undefined,
        chat_id: browseMode === 'chat' ? selectedChatId || undefined : undefined,
        chat_ids: selectedGroup && !selectedGroup.is_global ? selectedGroup.chat_ids : undefined,
        include_legacy: showLegacyExpressions,
      })
      if (result.success) {
        setExpressions(result.data.data)
        setTotal(result.data.total)
      } else {
        toast({
          title: '加载失败',
          description: result.error,
          variant: 'destructive',
        })
      }
    } catch (error) {
      toast({
        title: '加载失败',
        description: error instanceof Error ? error.message : '无法加载表达方式',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }

  // 加载统计数据
  const loadStats = async () => {
    try {
      const result = await getExpressionStats({ include_legacy: showLegacyExpressions })
      if (result.success) {
        setStats(result.data)
      } else {
        console.error('加载统计数据失败:', result.error)
      }
    } catch (error) {
      console.error('加载统计数据失败:', error)
    }
  }

  // 加载审核统计
  const loadReviewStats = async () => {
    try {
      const result = await getReviewStats()
      if (result.success) {
        setUncheckedCount(result.data.unchecked)
      }
    } catch (error) {
      console.error('加载审核统计失败:', error)
    }
  }

  // 加载聚天列表
  const loadChatList = async () => {
    try {
      const result = await getChatList({ include_legacy: showLegacyExpressions })
      if (result.success) {
        setChatList(result.data)
        const nameMap = new Map<string, string>()
        result.data.forEach((chat: ChatInfo) => {
          nameMap.set(chat.chat_id, chat.chat_name)
        })
        setChatNameMap(nameMap)
      }
    } catch (error) {
      console.error('加载聚天列表失败:', error)
    }
  }

  // 初始加载
  const loadExpressionGroups = async () => {
    try {
      const result = await getExpressionGroups({ include_legacy: showLegacyExpressions })
      if (result.success) {
        setExpressionGroups(result.data)
      }
    } catch (error) {
      console.error('鍔犺浇琛ㄨ揪浜掗€氱粍澶辫触:', error)
    }
  }

  useEffect(() => {
    loadExpressions()
    loadReviewStats()
    loadStats()
    loadChatList()
    loadExpressionGroups()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, browseMode, selectedChatId, selectedGroupIndex, showLegacyExpressions])

  // 查看详情
  const handleViewDetail = async (expression: Expression) => {
    try {
      const result = await getExpressionDetail(expression.id)
      if (result.success) {
        setSelectedExpression(result.data)
        setIsDetailDialogOpen(true)
      } else {
        toast({
          title: '加载详情失败',
          description: result.error,
          variant: 'destructive',
        })
      }
    } catch (error) {
      toast({
        title: '加载详情失败',
        description: error instanceof Error ? error.message : '无法加载表达方式详情',
        variant: 'destructive',
      })
    }
  }

  // 编辑表达方式
  const handleEdit = (expression: Expression) => {
    setSelectedExpression(expression)
    setIsEditDialogOpen(true)
  }

  // 删除表达方式
  const handleDelete = async () => {
    if (!deleteConfirmExpression) return
    try {
      const result = await deleteExpression(deleteConfirmExpression.id)
      if (result.success) {
        toast({
          title: '删除成功',
          description: `已删除表达方式: ${deleteConfirmExpression.situation}`,
        })
        setDeleteConfirmExpression(null)
        loadExpressions()
        loadStats()
      } else {
        toast({
          title: '删除失败',
          description: result.error,
          variant: 'destructive',
        })
      }
    } catch (error) {
      toast({
        title: '删除失败',
        description: error instanceof Error ? error.message : '无法删除表达方式',
        variant: 'destructive',
      })
    }
  }

  // 切换单个选择
  const toggleSelect = (id: number) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      newSelected.add(id)
    }
    setSelectedIds(newSelected)
  }

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedIds.size === expressions.length && expressions.length > 0) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(expressions.map(e => e.id)))
    }
  }

  // 批量删除
  const handleBatchDelete = async () => {
    try {
      const result = await batchDeleteExpressions(Array.from(selectedIds))
      if (result.success) {
        toast({
          title: '批量删除成功',
          description: `已删除 ${selectedIds.size} 个表达方式`,
        })
        setSelectedIds(new Set())
        setIsBatchDeleteDialogOpen(false)
        loadExpressions()
        loadStats()
      } else {
        toast({
          title: '批量删除失败',
          description: result.error,
          variant: 'destructive',
        })
      }
    } catch (error) {
      toast({
        title: '批量删除失败',
        description: error instanceof Error ? error.message : '无法批量删除表达方式',
        variant: 'destructive',
      })
    }
  }

  // 页面跳转
  const handleJumpToPage = (jumpToPage: string) => {
    const targetPage = parseInt(jumpToPage)
    const totalPages = Math.ceil(total / pageSize)
    if (targetPage >= 1 && targetPage <= totalPages) {
      setPage(targetPage)
    }
  }

  const handleChatChange = (chatId: string) => {
    setSelectedChatId(chatId)
    setPage(1)
    setSelectedIds(new Set())
  }

  const handleBrowseModeChange = (mode: 'chat' | 'group' | 'all') => {
    setBrowseMode(mode)
    if (mode === 'chat' && !selectedChatId && chatList.length > 0) {
      setSelectedChatId(chatList[0].chat_id)
    }
    if (mode !== 'chat') {
      setSelectedChatId('')
    }
    if (mode === 'group' && selectedGroupIndex === null && expressionGroups.length > 0) {
      setSelectedGroupIndex(expressionGroups[0].index)
    }
    if (mode !== 'group') {
      setSelectedGroupIndex(null)
    }
    setPage(1)
    setSelectedIds(new Set())
  }

  const handleGroupChange = (groupIndex: number | null) => {
    setSelectedGroupIndex(groupIndex)
    setPage(1)
    setSelectedIds(new Set())
  }

  const handleToggleLegacyExpressions = () => {
    setShowLegacyExpressions((current) => !current)
    setSelectedChatId('')
    setSelectedGroupIndex(null)
    setPage(1)
    setSelectedIds(new Set())
  }

  const summarizeStatus = (values: boolean[]): IndicatorStatus => {
    if (values.every(Boolean)) {
      return 'on'
    }
    if (values.every((value) => !value)) {
      return 'off'
    }
    return 'mixed'
  }

  const getScopeStatus = (): ExpressionLearningScopeStatus | null => {
    if (browseMode === 'chat' && selectedChatId) {
      const selectedChat = chatList.find((chat) => chat.chat_id === selectedChatId)
      if (!selectedChat) {
        return null
      }
      return {
        label: selectedChat.chat_name,
        useExpression: selectedChat.use_expression ? 'on' : 'off',
        enableLearning: selectedChat.enable_learning ? 'on' : 'off',
      }
    }

    if (browseMode === 'group' && selectedGroupIndex !== null) {
      const selectedGroup = expressionGroups.find((group) => group.index === selectedGroupIndex)
      if (!selectedGroup || selectedGroup.members.length === 0) {
        return null
      }
      return {
        label: selectedGroup.name,
        useExpression: summarizeStatus(selectedGroup.members.map((member) => member.use_expression)),
        enableLearning: summarizeStatus(selectedGroup.members.map((member) => member.enable_learning)),
      }
    }

    return null
  }

  const scopeStatus = getScopeStatus()
  const renderStatusIndicator = (label: string, status: IndicatorStatus) => {
    const statusText = status === 'mixed' ? '部分开启' : status === 'on' ? '已开启' : '已关闭'
    const dotClass = status === 'mixed' ? 'bg-amber-500' : status === 'on' ? 'bg-green-500' : 'bg-muted-foreground'

    return (
      <div className="flex items-center gap-2 rounded-md border bg-background px-3 py-1.5 text-sm">
        <span className={`h-2.5 w-2.5 rounded-full ${dotClass}`} />
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium">{statusText}</span>
      </div>
    )
  }

  const currentChat = browseMode === 'chat' && selectedChatId
    ? chatList.find((chat) => chat.chat_id === selectedChatId)
    : null

  const getImportExportChatId = (): string | null => {
    if (!currentChat) {
      toast({
        title: '请选择聊天',
        description: '表达方式导入导出需要先在左侧选择一个具体聊天',
        variant: 'destructive',
      })
      return null
    }
    return currentChat.chat_id
  }

  const downloadJson = (filename: string, data: unknown) => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  const sanitizeFilename = (name: string) => {
    return name.replace(/[\\/:*?"<>|]/g, '_').slice(0, 60) || 'chat'
  }

  const handleExportExpressions = async (onlySelected: boolean) => {
    const chatId = getImportExportChatId()
    if (!chatId || !currentChat) return
    if (onlySelected && selectedIds.size === 0) {
      toast({
        title: '没有选中项目',
        description: '请先选择要导出的表达方式',
        variant: 'destructive',
      })
      return
    }

    const result = await exportExpressions({
      chat_id: chatId,
      ids: onlySelected ? Array.from(selectedIds) : undefined,
    })
    if (!result.success) {
      toast({
        title: '导出失败',
        description: result.error,
        variant: 'destructive',
      })
      return
    }

    const filename = `expressions-${sanitizeFilename(currentChat.chat_name)}-${onlySelected ? 'selected' : 'all'}.json`
    downloadJson(filename, result.data)
    toast({
      title: '导出成功',
      description: `已导出 ${result.data.count} 个表达方式`,
    })
  }

  const normalizeImportItems = (payload: unknown): ExpressionExportItem[] => {
    if (Array.isArray(payload)) {
      return payload as ExpressionExportItem[]
    }
    if (payload && typeof payload === 'object' && Array.isArray((payload as { expressions?: unknown }).expressions)) {
      return (payload as { expressions: ExpressionExportItem[] }).expressions
    }
    return []
  }

  const handleImportFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const chatId = getImportExportChatId()
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!chatId || !file) return

    try {
      const payload = JSON.parse(await file.text()) as unknown
      const expressionsToImport = normalizeImportItems(payload)
      if (expressionsToImport.length === 0) {
        toast({
          title: '导入失败',
          description: 'JSON 中没有可导入的表达方式',
          variant: 'destructive',
        })
        return
      }

      const result = await importExpressions({
        chat_id: chatId,
        expressions: expressionsToImport,
      })
      if (!result.success) {
        toast({
          title: '导入失败',
          description: result.error,
          variant: 'destructive',
        })
        return
      }

      toast({
        title: '导入成功',
        description: `成功 ${result.data.imported_count} 个，跳过 ${result.data.skipped_count} 个，失败 ${result.data.failed_count} 个`,
      })
      loadExpressions()
      loadStats()
      loadReviewStats()
    } catch (error) {
      toast({
        title: '导入失败',
        description: error instanceof Error ? error.message : '无法解析 JSON 文件',
        variant: 'destructive',
      })
    }
  }

  const handleClearCurrentChat = async () => {
    const chatId = getImportExportChatId()
    if (!chatId) return

    const result = await clearExpressions({ chat_id: chatId })
    if (!result.success) {
      toast({
        title: '清除失败',
        description: result.error,
        variant: 'destructive',
      })
      return
    }

    toast({
      title: '清除成功',
      description: result.data.message,
    })
    setSelectedIds(new Set())
    setIsClearConfirmOpen(false)
    loadExpressions()
    loadStats()
    loadReviewStats()
  }

  return (
    <div className="h-[calc(100vh-4rem)] flex flex-col p-4 sm:p-6">
      {/* 页面标题 */}
      <div className="mb-4 sm:mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold flex items-center gap-2">
              <MessageSquare className="h-8 w-8" strokeWidth={2} />
              表达方式
            </h1>
            <p className="text-muted-foreground mt-1 text-sm sm:text-base">
              管理麦麦的表达方式和话术模板
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button 
              variant="outline" 
              onClick={() => setIsReviewerOpen(true)} 
              className="gap-2"
            >
              <ClipboardCheck className="h-4 w-4" />
              人工审核
              {uncheckedCount > 0 && (
                <span className="ml-1 px-1.5 py-0.5 text-xs rounded-full bg-orange-500 text-white">
                  {uncheckedCount > 99 ? '99+' : uncheckedCount}
                </span>
              )}
            </Button>
            <Button onClick={() => setIsCreateDialogOpen(true)} className="gap-2">
              <Plus className="h-4 w-4" />
              新增表达方式
            </Button>
            <Button variant="outline" onClick={() => setIsLegacyImportOpen(true)} className="gap-2">
              <Upload className="h-4 w-4" />
              从旧版本导入
            </Button>
          </div>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-4 sm:space-y-6 pr-4">

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-lg border bg-card px-4 py-3">
          <div className="text-xs text-muted-foreground">总数量</div>
          <div className="text-xl font-bold mt-0.5">{stats.total}</div>
        </div>
        <div className="rounded-lg border bg-card px-4 py-3">
          <div className="text-xs text-muted-foreground">近7天新增</div>
          <div className="text-xl font-bold mt-0.5 text-green-600">{stats.recent_7days}</div>
        </div>
        <div className="rounded-lg border bg-card px-4 py-3">
          <div className="text-xs text-muted-foreground">关联聊天数</div>
          <div className="text-xl font-bold mt-0.5 text-blue-600">{stats.chat_count}</div>
        </div>
      </div>

      {/* 搜索和批量操作 */}
      <div className="rounded-lg border bg-card p-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="flex-1">
            <Label htmlFor="search">搜索</Label>
            <div className="relative mt-1">
              <Search className="absolute left-2.5 top-2 h-4 w-4 text-muted-foreground" />
              <Input
                id="search"
                placeholder="搜索情境、风格或上下文..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-8 pl-9"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-2 text-xs text-muted-foreground"
              title="显示旧格式的表达方式（这些项目会在运行中被转换为新格式）"
              onClick={handleToggleLegacyExpressions}
            >
              {showLegacyExpressions ? '隐藏旧格式' : '显示旧格式'}
            </Button>
            <Label htmlFor="page-size" className="text-sm whitespace-nowrap">每页显示</Label>
            <Select
              value={pageSize.toString()}
              onValueChange={(value) => {
                setPageSize(parseInt(value))
                setPage(1)
                setSelectedIds(new Set())
              }}
            >
              <SelectTrigger id="page-size" className="h-8 w-20">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="10">10</SelectItem>
                <SelectItem value="20">20</SelectItem>
                <SelectItem value="50">50</SelectItem>
                <SelectItem value="100">100</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* 批量操作工具栏 */}
        <div className={`${selectedIds.size > 0 ? 'flex' : 'hidden'} flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mt-3 pt-3 border-t`}>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            {selectedIds.size > 0 && (
              <span>已选择 {selectedIds.size} 个表达方式</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {selectedIds.size > 0 && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedIds(new Set())}
                >
                  取消选择
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setIsBatchDeleteDialogOpen(true)}
                >
                  <Trash2 className="h-4 w-4 mr-1" />
                  批量删除
                </Button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* 表达方式列表 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <aside className="rounded-lg border bg-card lg:sticky lg:top-0 lg:max-h-[calc(100vh-18rem)]">
          <div className="space-y-2 border-b px-3 py-2">
            <h2 className="text-sm font-medium">浏览方式</h2>
            <div className="grid grid-cols-3 gap-1 rounded-md bg-muted p-1">
              <button
                type="button"
                onClick={() => handleBrowseModeChange('chat')}
                className={`rounded px-2 py-1 text-xs transition-colors ${
                  browseMode === 'chat' ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                按聊天
              </button>
              <button
                type="button"
                onClick={() => handleBrowseModeChange('group')}
                className={`rounded px-2 py-1 text-xs transition-colors ${
                  browseMode === 'group' ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                按互通组
              </button>
              <button
                type="button"
                onClick={() => handleBrowseModeChange('all')}
                className={`rounded px-2 py-1 text-xs transition-colors ${
                  browseMode === 'all' ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                全部
              </button>
            </div>
          </div>
          <div className="max-h-56 space-y-1 overflow-y-auto p-2 lg:max-h-[calc(100vh-21rem)]">
            {browseMode === 'chat' ? (
              <>
            {chatList.map((chat) => (
              <button
                key={chat.chat_id}
                type="button"
                onClick={() => handleChatChange(chat.chat_id)}
                className={`w-full rounded-md px-2 py-2 text-left text-sm transition-colors ${
                  selectedChatId === chat.chat_id
                    ? 'bg-primary text-primary-foreground'
                    : 'text-foreground hover:bg-muted'
                }`}
                title={`${chat.chat_name} (${chat.chat_id})`}
              >
                <span className="block truncate">{chat.chat_name}</span>
                <span
                  className={`block truncate text-xs ${
                    selectedChatId === chat.chat_id ? 'text-primary-foreground/75' : 'text-muted-foreground'
                  }`}
                >
                  {chat.chat_id}
                </span>
              </button>
            ))}
              </>
            ) : browseMode === 'group' ? (
              <>
                {expressionGroups.map((group) => (
                  <button
                    key={group.index}
                    type="button"
                    onClick={() => handleGroupChange(group.index)}
                    className={`w-full rounded-md px-2 py-2 text-left text-sm transition-colors ${
                      selectedGroupIndex === group.index
                        ? 'bg-primary text-primary-foreground'
                        : 'text-foreground hover:bg-muted'
                    }`}
                    title={group.members.map((member) => member.chat_name).join('、')}
                  >
                    <span className="block truncate">
                      {group.name}{group.is_global ? '（全局）' : ''}
                    </span>
                    <span
                      className={`block truncate text-xs ${
                        selectedGroupIndex === group.index ? 'text-primary-foreground/75' : 'text-muted-foreground'
                      }`}
                    >
                      {group.members.length > 0
                        ? group.members.map((member) => member.chat_name).join('、')
                        : '暂无已解析聊天'}
                    </span>
                  </button>
                ))}
                {expressionGroups.length === 0 && (
                  <div className="px-2 py-6 text-center text-sm text-muted-foreground">
                    暂无互通组
                  </div>
                )}
              </>
            ) : (
              <div className="px-2 py-6 text-center text-sm text-muted-foreground">
                当前显示全部表达方式
              </div>
            )}
          </div>
        </aside>

        <div className="space-y-3">
          {scopeStatus && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3 py-2">
              <div className="mr-2 min-w-0 text-sm font-medium">
                <span className="text-muted-foreground">当前范围：</span>
                <span>{scopeStatus.label}</span>
              </div>
              {renderStatusIndicator('开启学习', scopeStatus.enableLearning)}
              {renderStatusIndicator('开启使用', scopeStatus.useExpression)}
              {currentChat && (
                <div className="ml-auto flex flex-wrap items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1"
                    onClick={() => handleExportExpressions(false)}
                  >
                    <Download className="h-4 w-4" />
                    导出全部
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1"
                    onClick={() => handleExportExpressions(true)}
                    disabled={selectedIds.size === 0}
                  >
                    <Download className="h-4 w-4" />
                    导出所选
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1"
                    onClick={() => importInputRef.current?.click()}
                  >
                    <Upload className="h-4 w-4" />
                    导入 JSON
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    className="h-8"
                    onClick={() => setIsClearConfirmOpen(true)}
                  >
                    清除
                  </Button>
                  <input
                    ref={importInputRef}
                    type="file"
                    accept="application/json,.json"
                    className="hidden"
                    onChange={handleImportFileChange}
                  />
                </div>
              )}
            </div>
          )}

          <ExpressionList
            expressions={expressions}
            loading={loading}
            total={total}
            page={page}
            pageSize={pageSize}
            selectedIds={selectedIds}
            chatNameMap={chatNameMap}
            hideChatColumn={
              (browseMode === 'chat' && selectedChatId !== '') ||
              (browseMode === 'group' && selectedGroupIndex !== null)
            }
            onEdit={handleEdit}
            onViewDetail={handleViewDetail}
            onDelete={(expression) => setDeleteConfirmExpression(expression)}
            onToggleSelect={toggleSelect}
            onToggleSelectAll={toggleSelectAll}
            onPageChange={setPage}
            onJumpToPage={handleJumpToPage}
          />
        </div>
      </div>

        </div>
      </ScrollArea>

      {/* 详情对话框 */}
      <ExpressionDetailDialog
        expression={selectedExpression}
        open={isDetailDialogOpen}
        onOpenChange={setIsDetailDialogOpen}
        chatNameMap={chatNameMap}
      />

      {/* 创建对话框 */}
      <ExpressionCreateDialog
        open={isCreateDialogOpen}
        onOpenChange={setIsCreateDialogOpen}
        chatList={chatList}
        onSuccess={() => {
          loadExpressions()
          loadStats()
          setIsCreateDialogOpen(false)
        }}
      />

      {/* 编辑对话框 */}
      <ExpressionEditDialog
        expression={selectedExpression}
        open={isEditDialogOpen}
        onOpenChange={setIsEditDialogOpen}
        chatList={chatList}
        onSuccess={() => {
          loadExpressions()
          loadStats()
          setIsEditDialogOpen(false)
        }}
      />

      <LegacyExpressionImportDialog
        open={isLegacyImportOpen}
        onOpenChange={setIsLegacyImportOpen}
        chatList={chatList}
        onSuccess={() => {
          loadExpressions()
          loadStats()
          loadReviewStats()
          loadChatList()
          loadExpressionGroups()
        }}
      />

      {/* 删除确认对话框 */}
      <DeleteConfirmDialog
        expression={deleteConfirmExpression}
        open={!!deleteConfirmExpression}
        onOpenChange={() => setDeleteConfirmExpression(null)}
        onConfirm={handleDelete}
      />

      {/* 批量删除确认对话框 */}
      <BatchDeleteConfirmDialog
        open={isBatchDeleteDialogOpen}
        onOpenChange={setIsBatchDeleteDialogOpen}
        onConfirm={handleBatchDelete}
        count={selectedIds.size}
      />

      <ClearChatExpressionsConfirmDialog
        open={isClearConfirmOpen}
        onOpenChange={setIsClearConfirmOpen}
        chatName={currentChat?.chat_name || ''}
        onConfirm={handleClearCurrentChat}
      />

      {/* 表达方式审核器 */}
      <ExpressionReviewer
        open={isReviewerOpen}
        onOpenChange={(open) => {
          setIsReviewerOpen(open)
          if (!open) {
            loadExpressions()
            loadStats()
            loadReviewStats()
          }
        }}
      />
    </div>
  )
}
