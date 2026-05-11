import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  Database,
  Gauge,
  Loader2,
  RefreshCw,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  Upload,
  CheckCircle2,
  CircleAlert,
  FolderOpen,
  HardDrive,
} from 'lucide-react'

import { CodeEditor } from '@/components/CodeEditor'
import { MemoryDeleteDialog } from '@/components/memory/MemoryDeleteDialog'
import { MemoryEpisodeManager } from '@/components/memory/MemoryEpisodeManager'
import { MemoryMaintenanceManager } from '@/components/memory/MemoryMaintenanceManager'
import { MemoryMiniTabs } from '@/components/memory/MemoryMiniTabs'
import { MemoryProfileManager } from '@/components/memory/MemoryProfileManager'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/hooks/use-toast'
import { memoryProgressClient, type MemoryProgressEvent } from '@/lib/memory-progress-client'
import { cn } from '@/lib/utils'
import {
  cancelMemoryImportTask,
  createMemoryLpmmConvertImport,
  createMemoryLpmmOpenieImport,
  createMemoryMaibotMigrationImport,
  createMemoryRawScanImport,
  createMemoryTemporalBackfillImport,
  executeMemoryDelete,
  getMemoryFeedbackCorrection,
  getMemoryFeedbackCorrections,
  getMemoryImportPathAliases,
  getMemoryImportSettings,
  getMemoryImportTask,
  getMemoryImportTaskChunks,
  applyBestMemoryTuningProfile,
  createMemoryPasteImport,
  createMemoryTuningTask,
  createMemoryUploadImport,
  getMemoryDeleteOperation,
  getMemoryDeleteOperations,
  getMemoryImportTasks,
  getMemoryRuntimeConfig,
  getMemorySources,
  getMemoryTuningProfile,
  getMemoryTuningTasks,
  type MemoryDeleteRequestPayload,
  type MemoryImportChunkListPayload,
  type MemoryImportInputMode,
  type MemoryImportSettings,
  type MemoryImportTaskKind,
  type MemoryImportTaskPayload,
  previewMemoryDelete,
  refreshMemoryRuntimeSelfCheck,
  rollbackMemoryFeedbackCorrection,
  resolveMemoryImportPath,
  retryMemoryImportTask,
  restoreMemoryDelete,
  type MemoryDeleteExecutePayload,
  type MemoryDeleteOperationPayload,
  type MemoryFeedbackActionLogPayload,
  type MemoryFeedbackCorrectionDetailTaskPayload,
  type MemoryFeedbackCorrectionSummaryPayload,
  type MemorySourceItemPayload,
  type MemoryRuntimeConfigPayload,
  type MemoryTaskPayload,
} from '@/lib/memory-api'

import {
  DELETE_OPERATION_FETCH_LIMIT,
  DELETE_OPERATION_ITEM_PAGE_SIZE,
  DELETE_OPERATION_PAGE_SIZE,
  FEEDBACK_ACTION_LOG_PAGE_SIZE,
  FEEDBACK_CORRECTION_FETCH_LIMIT,
  FEEDBACK_CORRECTION_PAGE_SIZE,
  IMPORT_CHUNK_PAGE_SIZE,
  QUEUED_IMPORT_STATUS,
  RUNNING_IMPORT_STATUS,
} from './knowledge-base/constants'
import {
  buildFeedbackImpactSummary,
  getFeedbackCorrectionPreview,
  parseCommaSeparatedList,
  parseOptionalPositiveInt,
  summarizeFeedbackActionPayload,
} from './knowledge-base/utils'
import { DeleteTab } from './knowledge-base/tabs/DeleteTab'
import { FeedbackTab } from './knowledge-base/tabs/FeedbackTab'
import { ImportTab } from './knowledge-base/tabs/ImportTab'
import { TuningTab } from './knowledge-base/tabs/TuningTab'
import { KnowledgeGraphPage } from './knowledge-graph'

const DATE_TIME_LOCAL_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?$/
const POSITIVE_INTEGER_PATTERN = /^[1-9]\d*$/

function parseMaibotPositiveInt(input: string, fieldName: string): number | undefined {
  const value = input.trim()
  if (!value) {
    return undefined
  }
  if (!POSITIVE_INTEGER_PATTERN.test(value)) {
    throw new Error(`${fieldName} 必须填写正整数`)
  }
  const parsed = Number(value)
  if (!Number.isSafeInteger(parsed)) {
    throw new Error(`${fieldName} 超过可支持的整数范围`)
  }
  return parsed
}

function getMaibotDateTimeLocalTimestamp(input: string, fieldName: string): number | undefined {
  const value = input.trim()
  if (!value) {
    return undefined
  }
  if (!DATE_TIME_LOCAL_PATTERN.test(value)) {
    throw new Error(`${fieldName}格式无效，请使用时间选择器填写`)
  }
  const timestamp = new Date(value).getTime()
  if (!Number.isFinite(timestamp)) {
    throw new Error(`${fieldName}不是有效时间`)
  }
  return timestamp
}

function formatMaibotDateTimeLocalForApi(input: string, fieldName: string): string | undefined {
  const value = input.trim()
  if (!value) {
    return undefined
  }
  if (!DATE_TIME_LOCAL_PATTERN.test(value)) {
    throw new Error(`${fieldName}格式无效，请使用时间选择器填写`)
  }
  const date = new Date(value)
  const timestamp = date.getTime()
  if (!Number.isFinite(timestamp)) {
    throw new Error(`${fieldName}不是有效时间`)
  }
  return date.toISOString()
}

export function KnowledgeBasePage() {
  const { toast } = useToast()
  const [loading, setLoading] = useState(true)
  const [refreshingCheck, setRefreshingCheck] = useState(false)
  const [creatingImport, setCreatingImport] = useState(false)
  const [creatingTuning, setCreatingTuning] = useState(false)
  const [activeTab, setActiveTab] = useState<
    'overview' | 'graph' | 'import' | 'tuning' | 'episodes' | 'profiles' | 'maintenance' | 'delete' | 'feedback'
  >('overview')
  const [visitedMemoryTabs, setVisitedMemoryTabs] = useState<Set<string>>(() => new Set())

  const [runtimeConfig, setRuntimeConfig] = useState<MemoryRuntimeConfigPayload | null>(null)
  const [selfCheckReport, setSelfCheckReport] = useState<Record<string, unknown> | null>(null)
  const [importSettings, setImportSettings] = useState<MemoryImportSettings>({})
  const [importPathAliases, setImportPathAliases] = useState<Record<string, string>>({})
  const [importTasks, setImportTasks] = useState<MemoryImportTaskPayload[]>([])
  const [selectedImportTaskId, setSelectedImportTaskId] = useState('')
  const [selectedImportTask, setSelectedImportTask] = useState<MemoryImportTaskPayload | null>(null)
  const [selectedImportTaskLoading, setSelectedImportTaskLoading] = useState(false)
  const [selectedImportFileId, setSelectedImportFileId] = useState('')
  const [importChunkOffset, setImportChunkOffset] = useState(0)
  const [importChunksPayload, setImportChunksPayload] = useState<MemoryImportChunkListPayload | null>(null)
  const [importChunksLoading, setImportChunksLoading] = useState(false)
  const [importCreateMode, setImportCreateMode] = useState<MemoryImportTaskKind>('upload')
  const [importAutoPolling, setImportAutoPolling] = useState(true)
  const [importErrorText, setImportErrorText] = useState('')
  const [importCommonFileConcurrency, setImportCommonFileConcurrency] = useState('2')
  const [importCommonChunkConcurrency, setImportCommonChunkConcurrency] = useState('4')
  const [importCommonLlmEnabled, setImportCommonLlmEnabled] = useState(true)
  const [importCommonStrategyOverride, setImportCommonStrategyOverride] = useState('auto')
  const [importCommonDedupePolicy, setImportCommonDedupePolicy] = useState('content_hash')
  const [importCommonChatLog, setImportCommonChatLog] = useState(false)
  const [importCommonChatReferenceTime, setImportCommonChatReferenceTime] = useState('')
  const [importCommonForce, setImportCommonForce] = useState(false)
  const [importCommonClearManifest, setImportCommonClearManifest] = useState(false)

  const [uploadInputMode, setUploadInputMode] = useState<MemoryImportInputMode>('text')
  const [uploadFiles, setUploadFiles] = useState<File[]>([])

  const [pasteName, setPasteName] = useState('')
  const [pasteMode, setPasteMode] = useState<MemoryImportInputMode>('text')
  const [pasteContent, setPasteContent] = useState('')

  const [rawAlias, setRawAlias] = useState('raw')
  const [rawRelativePath, setRawRelativePath] = useState('')
  const [rawGlob, setRawGlob] = useState('*')
  const [rawInputMode, setRawInputMode] = useState<MemoryImportInputMode>('text')
  const [rawRecursive, setRawRecursive] = useState(true)

  const [openieAlias, setOpenieAlias] = useState('lpmm')
  const [openieRelativePath, setOpenieRelativePath] = useState('')
  const [openieIncludeAllJson, setOpenieIncludeAllJson] = useState(false)

  const [convertAlias, setConvertAlias] = useState('lpmm')
  const [convertRelativePath, setConvertRelativePath] = useState('')
  const [convertTargetAlias, setConvertTargetAlias] = useState('plugin_data')
  const [convertTargetRelativePath, setConvertTargetRelativePath] = useState('')
  const [convertDimension, setConvertDimension] = useState('')
  const [convertBatchSize, setConvertBatchSize] = useState('1024')

  const [backfillAlias, setBackfillAlias] = useState('plugin_data')
  const [backfillRelativePath, setBackfillRelativePath] = useState('')
  const [backfillLimit, setBackfillLimit] = useState('100000')
  const [backfillDryRun, setBackfillDryRun] = useState(false)
  const [backfillNoCreatedFallback, setBackfillNoCreatedFallback] = useState(false)

  const [maibotSourceDb, setMaibotSourceDb] = useState('')
  const [maibotTimeFrom, setMaibotTimeFrom] = useState('')
  const [maibotTimeTo, setMaibotTimeTo] = useState('')
  const [maibotStartId, setMaibotStartId] = useState('')
  const [maibotEndId, setMaibotEndId] = useState('')
  const [maibotStreamIds, setMaibotStreamIds] = useState('')
  const [maibotGroupIds, setMaibotGroupIds] = useState('')
  const [maibotUserIds, setMaibotUserIds] = useState('')
  const [maibotReadBatchSize, setMaibotReadBatchSize] = useState('2000')
  const [maibotCommitWindowRows, setMaibotCommitWindowRows] = useState('20000')
  const [maibotEmbedWorkers, setMaibotEmbedWorkers] = useState('')
  const [maibotNoResume, setMaibotNoResume] = useState(false)
  const [maibotResetState, setMaibotResetState] = useState(false)
  const [maibotDryRun, setMaibotDryRun] = useState(false)
  const [maibotVerifyOnly, setMaibotVerifyOnly] = useState(false)
  const maibotSourceDbDefaultAppliedRef = useRef(false)

  const [pathResolveAlias, setPathResolveAlias] = useState('raw')
  const [pathResolveRelativePath, setPathResolveRelativePath] = useState('')
  const [pathResolveMustExist, setPathResolveMustExist] = useState(true)
  const [pathResolveOutput, setPathResolveOutput] = useState('')
  const [resolvingPath, setResolvingPath] = useState(false)

  const [tuningTasks, setTuningTasks] = useState<MemoryTaskPayload[]>([])
  const [tuningProfile, setTuningProfile] = useState<Record<string, unknown>>({})
  const [tuningProfileToml, setTuningProfileToml] = useState('')
  const [memorySources, setMemorySources] = useState<MemorySourceItemPayload[]>([])
  const [deleteOperations, setDeleteOperations] = useState<MemoryDeleteOperationPayload[]>([])
  const [selectedOperationDetail, setSelectedOperationDetail] = useState<MemoryDeleteOperationPayload | null>(null)
  const [selectedOperationDetailLoading, setSelectedOperationDetailLoading] = useState(false)
  const [selectedOperationDetailError, setSelectedOperationDetailError] = useState('')
  const [sourceSearch, setSourceSearch] = useState('')
  const [operationSearch, setOperationSearch] = useState('')
  const [operationModeFilter, setOperationModeFilter] = useState('all')
  const [operationStatusFilter, setOperationStatusFilter] = useState('all')
  const [operationPage, setOperationPage] = useState(1)
  const [selectedOperationId, setSelectedOperationId] = useState('')
  const [selectedOperationItemSearch, setSelectedOperationItemSearch] = useState('')
  const [selectedOperationItemPage, setSelectedOperationItemPage] = useState(1)
  const [selectedSources, setSelectedSources] = useState<string[]>([])
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteDialogTitle, setDeleteDialogTitle] = useState('删除预览')
  const [deleteDialogDescription, setDeleteDialogDescription] = useState('')
  const [deletePreview, setDeletePreview] = useState<Awaited<ReturnType<typeof previewMemoryDelete>> | null>(null)
  const [deletePreviewError, setDeletePreviewError] = useState<string | null>(null)
  const [deletePreviewLoading, setDeletePreviewLoading] = useState(false)
  const [deleteExecuting, setDeleteExecuting] = useState(false)
  const [deleteRestoring, setDeleteRestoring] = useState(false)
  const [deleteResult, setDeleteResult] = useState<MemoryDeleteExecutePayload | null>(null)
  const [pendingDeleteRequest, setPendingDeleteRequest] = useState<MemoryDeleteRequestPayload | null>(null)
  const [feedbackCorrections, setFeedbackCorrections] = useState<MemoryFeedbackCorrectionSummaryPayload[]>([])
  const [feedbackSearch, setFeedbackSearch] = useState('')
  const [feedbackStatusFilter, setFeedbackStatusFilter] = useState('all')
  const [feedbackRollbackFilter, setFeedbackRollbackFilter] = useState('all')
  const [feedbackPage, setFeedbackPage] = useState(1)
  const [selectedFeedbackTaskId, setSelectedFeedbackTaskId] = useState(0)
  const [selectedFeedbackTaskDetail, setSelectedFeedbackTaskDetail] = useState<MemoryFeedbackCorrectionDetailTaskPayload | null>(null)
  const [selectedFeedbackTaskLoading, setSelectedFeedbackTaskLoading] = useState(false)
  const [selectedFeedbackTaskError, setSelectedFeedbackTaskError] = useState('')
  const [feedbackActionLogSearch, setFeedbackActionLogSearch] = useState('')
  const [feedbackActionLogPage, setFeedbackActionLogPage] = useState(1)
  const [feedbackRollbackDialogOpen, setFeedbackRollbackDialogOpen] = useState(false)
  const [feedbackRollbackReason, setFeedbackRollbackReason] = useState('')
  const [feedbackRollingBack, setFeedbackRollingBack] = useState(false)
  const [tuningObjective, setTuningObjective] = useState('precision_priority')
  const [tuningIntensity, setTuningIntensity] = useState('standard')
  const [tuningSampleSize, setTuningSampleSize] = useState('24')
  const [tuningTopKEval, setTuningTopKEval] = useState('20')

  const loadPage = useCallback(async () => {
    try {
      setLoading(true)
      const [
        runtimePayload,
        importSettingsPayload,
        pathAliasPayload,
        importTaskPayload,
        tuningProfilePayload,
        tuningTaskPayload,
        sourcePayload,
        deleteOperationPayload,
        feedbackCorrectionPayload,
      ] = await Promise.all([
        getMemoryRuntimeConfig(),
        getMemoryImportSettings(),
        getMemoryImportPathAliases(),
        getMemoryImportTasks(20),
        getMemoryTuningProfile(),
        getMemoryTuningTasks(20),
        getMemorySources(),
        getMemoryDeleteOperations(DELETE_OPERATION_FETCH_LIMIT),
        getMemoryFeedbackCorrections({ limit: FEEDBACK_CORRECTION_FETCH_LIMIT }),
      ])

      setRuntimeConfig(runtimePayload)
      setImportSettings(importSettingsPayload.settings ?? {})
      setImportPathAliases(pathAliasPayload.path_aliases ?? {})
      setImportTasks(importTaskPayload.items ?? [])
      setTuningProfile(tuningProfilePayload.profile ?? {})
      setTuningProfileToml(tuningProfilePayload.toml ?? '')
      setTuningTasks(tuningTaskPayload.items ?? [])
      setMemorySources(sourcePayload.items ?? [])
      setDeleteOperations(deleteOperationPayload.items ?? [])
      setFeedbackCorrections(feedbackCorrectionPayload.items ?? [])
      setSelectedImportTaskId((currentTaskId) => {
        if (currentTaskId || (importTaskPayload.items ?? []).length === 0) {
          return currentTaskId
        }
        const initialTaskId = String(importTaskPayload.items?.[0]?.task_id ?? '')
        return initialTaskId || currentTaskId
      })
      setPathResolveAlias((currentAlias) => {
        if (currentAlias) {
          return currentAlias
        }
        const aliasKeys = Object.keys(pathAliasPayload.path_aliases ?? {})
        return aliasKeys[0] ?? currentAlias
      })
    } catch (error) {
      toast({
        title: '加载长期记忆控制台失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    void loadPage()
  }, [loadPage])

  useEffect(() => {
    if (!['episodes', 'profiles', 'maintenance'].includes(activeTab)) {
      return
    }
    setVisitedMemoryTabs((current) => {
      if (current.has(activeTab)) {
        return current
      }
      const next = new Set(current)
      next.add(activeTab)
      return next
    })
  }, [activeTab])

  const runtimeBadges = useMemo(() => {
    if (!runtimeConfig) {
      return []
    }
    return [
      {
        label: '运行状态',
        value: runtimeConfig.runtime_ready ? '就绪' : '未就绪',
        description: runtimeConfig.embedding_degraded ? 'Embedding 降级运行' : '运行时检查通过',
        icon: runtimeConfig.runtime_ready ? CheckCircle2 : CircleAlert,
        className: runtimeConfig.runtime_ready ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-amber-500/20 bg-amber-500/5',
        iconClassName: runtimeConfig.runtime_ready ? 'text-emerald-500' : 'text-amber-500',
      },
      {
        label: 'Embedding 维度',
        value: String(runtimeConfig.embedding_dimension),
        description: runtimeConfig.relation_vectors_enabled ? '关系向量已启用' : '关系向量未启用',
        icon: HardDrive,
        className: 'border-sky-500/20 bg-sky-500/5',
        iconClassName: 'text-sky-500',
      },
      {
        label: '自动保存',
        value: runtimeConfig.auto_save ? '开启' : '关闭',
        description: runtimeConfig.auto_save ? '运行数据会自动落盘' : '请留意手动保存',
        icon: runtimeConfig.auto_save ? CheckCircle2 : CircleAlert,
        className: runtimeConfig.auto_save ? 'border-primary/20 bg-primary/5' : 'border-muted-foreground/20 bg-muted/30',
        iconClassName: runtimeConfig.auto_save ? 'text-primary' : 'text-muted-foreground',
      },
      {
        label: '数据目录',
        value: runtimeConfig.data_dir,
        description: '长期记忆存储位置',
        icon: FolderOpen,
        className: 'border-violet-500/20 bg-violet-500/5',
        iconClassName: 'text-violet-500',
      },
    ]
  }, [runtimeConfig])

  const importPollInterval = useMemo(
    () => Math.max(200, Number(importSettings.poll_interval_ms ?? 1000)),
    [importSettings.poll_interval_ms],
  )

  const importAliasKeys = useMemo(
    () => Object.keys(importPathAliases).sort((left, right) => left.localeCompare(right)),
    [importPathAliases],
  )

  const runningImportTasks = useMemo(
    () => importTasks.filter((task) => RUNNING_IMPORT_STATUS.has(String(task.status ?? '').trim())),
    [importTasks],
  )
  const queuedImportTasks = useMemo(
    () => importTasks.filter((task) => QUEUED_IMPORT_STATUS.has(String(task.status ?? '').trim())),
    [importTasks],
  )
  const recentImportTasks = useMemo(
    () =>
      importTasks.filter((task) => {
        const status = String(task.status ?? '').trim()
        return !RUNNING_IMPORT_STATUS.has(status) && !QUEUED_IMPORT_STATUS.has(status)
      }),
    [importTasks],
  )
  const selectedImportTaskSummary = useMemo(() => {
    if (!selectedImportTaskId) {
      return null
    }
    return importTasks.find((task) => task.task_id === selectedImportTaskId) ?? null
  }, [importTasks, selectedImportTaskId])

  const selectedImportFiles = useMemo(() => {
    return Array.isArray(selectedImportTask?.files) ? selectedImportTask.files : []
  }, [selectedImportTask?.files])

  const selectedImportChunks = useMemo(() => {
    return Array.isArray(importChunksPayload?.items) ? importChunksPayload.items : []
  }, [importChunksPayload?.items])

  const selectedImportTaskResolved = selectedImportTask ?? selectedImportTaskSummary
  const selectedImportTaskErrorText = String(selectedImportTaskResolved?.error ?? '').trim()
  const selectedImportRetrySummary = selectedImportTaskResolved?.retry_summary

  const importChunkTotal = Number(importChunksPayload?.total ?? 0)
  const canImportChunkPrev = importChunkOffset > 0
  const canImportChunkNext = importChunkOffset + IMPORT_CHUNK_PAGE_SIZE < importChunkTotal

  const buildCommonImportPayload = useCallback((): Record<string, unknown> => {
    const payload: Record<string, unknown> = {
      llm_enabled: importCommonLlmEnabled,
      strategy_override: importCommonStrategyOverride,
      dedupe_policy: importCommonDedupePolicy,
      chat_log: importCommonChatLog,
      force: importCommonForce,
      clear_manifest: importCommonClearManifest,
    }

    const fileConcurrency = parseOptionalPositiveInt(importCommonFileConcurrency)
    const chunkConcurrency = parseOptionalPositiveInt(importCommonChunkConcurrency)
    if (fileConcurrency !== undefined) {
      payload.file_concurrency = fileConcurrency
    }
    if (chunkConcurrency !== undefined) {
      payload.chunk_concurrency = chunkConcurrency
    }
    if (importCommonChatReferenceTime.trim()) {
      payload.chat_reference_time = importCommonChatReferenceTime.trim()
    }
    return payload
  }, [
    importCommonChatLog,
    importCommonChatReferenceTime,
    importCommonChunkConcurrency,
    importCommonClearManifest,
    importCommonDedupePolicy,
    importCommonFileConcurrency,
    importCommonForce,
    importCommonLlmEnabled,
    importCommonStrategyOverride,
  ])

  const refreshImportQueue = useCallback(async (silent: boolean = false) => {
    try {
      const [taskPayload, settingsPayload, pathAliasPayload] = await Promise.all([
        getMemoryImportTasks(20),
        getMemoryImportSettings(),
        getMemoryImportPathAliases(),
      ])
      const nextTasks = taskPayload.items ?? []
      setImportTasks(nextTasks)
      setImportSettings(settingsPayload.settings ?? {})
      setImportPathAliases(pathAliasPayload.path_aliases ?? {})
      setImportErrorText('')

      if (nextTasks.length <= 0) {
        setSelectedImportTaskId('')
        setSelectedImportTask(null)
        setSelectedImportFileId('')
        setImportChunksPayload(null)
        return
      }

      if (!selectedImportTaskId || !nextTasks.some((item) => item.task_id === selectedImportTaskId)) {
        setSelectedImportTaskId(nextTasks[0].task_id)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '刷新导入任务失败'
      setImportErrorText(message)
      if (!silent) {
        toast({
          title: '刷新导入任务失败',
          description: message,
          variant: 'destructive',
        })
      }
    }
  }, [selectedImportTaskId, toast])

  const loadImportChunks = useCallback(
    async (
      taskId: string,
      fileId: string,
      offset: number = 0,
      silent: boolean = false,
    ) => {
      if (!taskId || !fileId) {
        setImportChunksPayload(null)
        return
      }
      try {
        setImportChunksLoading(true)
        const payload = await getMemoryImportTaskChunks(taskId, fileId, offset, IMPORT_CHUNK_PAGE_SIZE)
        if (!payload.success) {
          throw new Error(payload.error || '加载分块详情失败')
        }
        setImportChunksPayload(payload)
        setImportErrorText('')
      } catch (error) {
        const message = error instanceof Error ? error.message : '加载分块详情失败'
        setImportChunksPayload(null)
        setImportErrorText(message)
        if (!silent) {
          toast({
            title: '加载分块详情失败',
            description: message,
            variant: 'destructive',
          })
        }
      } finally {
        setImportChunksLoading(false)
      }
    },
    [toast],
  )

  const loadImportTaskDetail = useCallback(
    async (taskId: string, silent: boolean = false) => {
      if (!taskId) {
        setSelectedImportTask(null)
        setSelectedImportFileId('')
        setImportChunksPayload(null)
        return
      }
      try {
        if (!silent) {
          setSelectedImportTaskLoading(true)
        }
        const payload = await getMemoryImportTask(taskId, false)
        if (!payload.success || !payload.task) {
          throw new Error(payload.error || '任务不存在')
        }
        const task = payload.task
        setSelectedImportTask(task)
        setImportErrorText('')
        const files = Array.isArray(task.files) ? task.files : []
        const keepCurrentFile = files.some((file) => file.file_id === selectedImportFileId)
        const nextFileId = keepCurrentFile ? selectedImportFileId : String(files[0]?.file_id ?? '')
        const nextOffset = keepCurrentFile ? importChunkOffset : 0
        if (!keepCurrentFile) {
          setImportChunkOffset(0)
        }
        setSelectedImportFileId(nextFileId)
        if (nextFileId) {
          await loadImportChunks(taskId, nextFileId, nextOffset, silent)
        } else {
          setImportChunksPayload(null)
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : '加载导入任务详情失败'
        setSelectedImportTask(null)
        setSelectedImportFileId('')
        setImportChunksPayload(null)
        setImportErrorText(message)
        if (!silent) {
          toast({
            title: '加载导入任务详情失败',
            description: message,
            variant: 'destructive',
          })
        }
      } finally {
        if (!silent) {
          setSelectedImportTaskLoading(false)
        }
      }
    },
    [importChunkOffset, loadImportChunks, selectedImportFileId, toast],
  )

  const afterImportTaskCreated = useCallback(
    async (taskId: string, successTitle: string) => {
      await refreshImportQueue(true)
      if (taskId) {
        setSelectedImportTaskId(taskId)
        await loadImportTaskDetail(taskId, true)
      }
      toast({
        title: successTitle,
        description: taskId ? `任务 ${taskId.slice(0, 12)} 已加入导入队列` : '导入任务已加入队列',
      })
    },
    [loadImportTaskDetail, refreshImportQueue, toast],
  )

  const submitUploadImport = useCallback(async () => {
    if (uploadFiles.length <= 0) {
      toast({
        title: '请选择上传文件',
        description: '至少选择一个 txt/md/json 文件后再提交',
        variant: 'destructive',
      })
      return
    }
    try {
      setCreatingImport(true)
      const payload = {
        ...buildCommonImportPayload(),
        input_mode: uploadInputMode,
      }
      const result = await createMemoryUploadImport(uploadFiles, payload)
      if (!result.success) {
        throw new Error(result.error || '创建上传导入任务失败')
      }
      const taskId = String(result.task?.task_id ?? '')
      setUploadFiles([])
      await afterImportTaskCreated(taskId, '上传导入任务已创建')
    } catch (error) {
      const message = error instanceof Error ? error.message : '创建上传导入任务失败'
      setImportErrorText(message)
      toast({
        title: '创建上传导入任务失败',
        description: message,
        variant: 'destructive',
      })
    } finally {
      setCreatingImport(false)
    }
  }, [afterImportTaskCreated, buildCommonImportPayload, toast, uploadFiles, uploadInputMode])

  const submitPasteImport = useCallback(async () => {
    if (!pasteContent.trim()) {
      toast({
        title: '粘贴内容不能为空',
        description: '请填写导入内容后再提交',
        variant: 'destructive',
      })
      return
    }
    try {
      setCreatingImport(true)
      const result = await createMemoryPasteImport({
        ...buildCommonImportPayload(),
        name: pasteName || undefined,
        content: pasteContent,
        input_mode: pasteMode,
      })
      if (!result.success) {
        throw new Error(result.error || '创建粘贴导入任务失败')
      }
      const taskId = String(result.task?.task_id ?? '')
      setPasteContent('')
      setPasteName('')
      await afterImportTaskCreated(taskId, '粘贴导入任务已创建')
    } catch (error) {
      const message = error instanceof Error ? error.message : '创建粘贴导入任务失败'
      setImportErrorText(message)
      toast({
        title: '创建粘贴导入任务失败',
        description: message,
        variant: 'destructive',
      })
    } finally {
      setCreatingImport(false)
    }
  }, [afterImportTaskCreated, buildCommonImportPayload, pasteContent, pasteMode, pasteName, toast])

  const submitRawScanImport = useCallback(async () => {
    try {
      setCreatingImport(true)
      const result = await createMemoryRawScanImport({
        ...buildCommonImportPayload(),
        alias: rawAlias,
        relative_path: rawRelativePath,
        glob: rawGlob,
        recursive: rawRecursive,
        input_mode: rawInputMode,
      })
      if (!result.success) {
        throw new Error(result.error || '创建本地扫描任务失败')
      }
      await afterImportTaskCreated(String(result.task?.task_id ?? ''), '本地扫描任务已创建')
    } catch (error) {
      const message = error instanceof Error ? error.message : '创建本地扫描任务失败'
      setImportErrorText(message)
      toast({
        title: '创建本地扫描任务失败',
        description: message,
        variant: 'destructive',
      })
    } finally {
      setCreatingImport(false)
    }
  }, [
    afterImportTaskCreated,
    buildCommonImportPayload,
    rawAlias,
    rawGlob,
    rawInputMode,
    rawRecursive,
    rawRelativePath,
    toast,
  ])

  const submitOpenieImport = useCallback(async () => {
    try {
      setCreatingImport(true)
      const result = await createMemoryLpmmOpenieImport({
        ...buildCommonImportPayload(),
        alias: openieAlias,
        relative_path: openieRelativePath,
        include_all_json: openieIncludeAllJson,
      })
      if (!result.success) {
        throw new Error(result.error || '创建 LPMM OpenIE 任务失败')
      }
      await afterImportTaskCreated(String(result.task?.task_id ?? ''), 'LPMM OpenIE 任务已创建')
    } catch (error) {
      const message = error instanceof Error ? error.message : '创建 LPMM OpenIE 任务失败'
      setImportErrorText(message)
      toast({
        title: '创建 LPMM OpenIE 任务失败',
        description: message,
        variant: 'destructive',
      })
    } finally {
      setCreatingImport(false)
    }
  }, [
    afterImportTaskCreated,
    buildCommonImportPayload,
    openieAlias,
    openieIncludeAllJson,
    openieRelativePath,
    toast,
  ])

  const submitConvertImport = useCallback(async () => {
    try {
      setCreatingImport(true)
      const result = await createMemoryLpmmConvertImport({
        alias: convertAlias,
        relative_path: convertRelativePath,
        target_alias: convertTargetAlias,
        target_relative_path: convertTargetRelativePath,
        dimension: parseOptionalPositiveInt(convertDimension),
        batch_size: parseOptionalPositiveInt(convertBatchSize),
      })
      if (!result.success) {
        throw new Error(result.error || '创建 LPMM 转换任务失败')
      }
      await afterImportTaskCreated(String(result.task?.task_id ?? ''), 'LPMM 转换任务已创建')
    } catch (error) {
      const message = error instanceof Error ? error.message : '创建 LPMM 转换任务失败'
      setImportErrorText(message)
      toast({
        title: '创建 LPMM 转换任务失败',
        description: message,
        variant: 'destructive',
      })
    } finally {
      setCreatingImport(false)
    }
  }, [
    afterImportTaskCreated,
    convertAlias,
    convertBatchSize,
    convertDimension,
    convertRelativePath,
    convertTargetAlias,
    convertTargetRelativePath,
    toast,
  ])

  const submitBackfillImport = useCallback(async () => {
    try {
      setCreatingImport(true)
      const result = await createMemoryTemporalBackfillImport({
        alias: backfillAlias,
        relative_path: backfillRelativePath,
        limit: parseOptionalPositiveInt(backfillLimit),
        dry_run: backfillDryRun,
        no_created_fallback: backfillNoCreatedFallback,
      })
      if (!result.success) {
        throw new Error(result.error || '创建时序回填任务失败')
      }
      await afterImportTaskCreated(String(result.task?.task_id ?? ''), '时序回填任务已创建')
    } catch (error) {
      const message = error instanceof Error ? error.message : '创建时序回填任务失败'
      setImportErrorText(message)
      toast({
        title: '创建时序回填任务失败',
        description: message,
        variant: 'destructive',
      })
    } finally {
      setCreatingImport(false)
    }
  }, [
    afterImportTaskCreated,
    backfillAlias,
    backfillDryRun,
    backfillLimit,
    backfillNoCreatedFallback,
    backfillRelativePath,
    toast,
  ])

  const submitMaibotMigrationImport = useCallback(async () => {
    try {
      setCreatingImport(true)
      const sourceDb = maibotSourceDb.trim()
      if (!sourceDb) {
        throw new Error('请填写源数据库路径')
      }
      const timeFromTimestamp = getMaibotDateTimeLocalTimestamp(maibotTimeFrom, '起始时间')
      const timeToTimestamp = getMaibotDateTimeLocalTimestamp(maibotTimeTo, '结束时间')
      if (
        timeFromTimestamp !== undefined &&
        timeToTimestamp !== undefined &&
        timeFromTimestamp > timeToTimestamp
      ) {
        throw new Error('起始时间不能晚于结束时间')
      }
      const startId = parseMaibotPositiveInt(maibotStartId, '起始 ID')
      const endId = parseMaibotPositiveInt(maibotEndId, '结束 ID')
      if (startId !== undefined && endId !== undefined && startId > endId) {
        throw new Error('起始 ID 不能大于结束 ID')
      }
      const result = await createMemoryMaibotMigrationImport({
        source_db: sourceDb,
        time_from: formatMaibotDateTimeLocalForApi(maibotTimeFrom, '起始时间'),
        time_to: formatMaibotDateTimeLocalForApi(maibotTimeTo, '结束时间'),
        start_id: startId,
        end_id: endId,
        stream_ids: parseCommaSeparatedList(maibotStreamIds),
        group_ids: parseCommaSeparatedList(maibotGroupIds),
        user_ids: parseCommaSeparatedList(maibotUserIds),
        read_batch_size: parseMaibotPositiveInt(maibotReadBatchSize, '读取批大小'),
        commit_window_rows: parseMaibotPositiveInt(maibotCommitWindowRows, '提交窗口行数'),
        embed_workers: parseMaibotPositiveInt(maibotEmbedWorkers, '向量线程数'),
        no_resume: maibotNoResume,
        reset_state: maibotResetState,
        dry_run: maibotDryRun,
        verify_only: maibotVerifyOnly,
      })
      if (!result.success) {
        throw new Error(result.error || '创建 MaiBot 迁移任务失败')
      }
      await afterImportTaskCreated(String(result.task?.task_id ?? ''), 'MaiBot 迁移任务已创建')
    } catch (error) {
      const message = error instanceof Error ? error.message : '创建 MaiBot 迁移任务失败'
      setImportErrorText(message)
      toast({
        title: '创建 MaiBot 迁移任务失败',
        description: message,
        variant: 'destructive',
      })
    } finally {
      setCreatingImport(false)
    }
  }, [
    afterImportTaskCreated,
    maibotCommitWindowRows,
    maibotDryRun,
    maibotEmbedWorkers,
    maibotEndId,
    maibotGroupIds,
    maibotNoResume,
    maibotReadBatchSize,
    maibotResetState,
    maibotSourceDb,
    maibotStartId,
    maibotStreamIds,
    maibotTimeFrom,
    maibotTimeTo,
    maibotUserIds,
    maibotVerifyOnly,
    toast,
  ])

  const cancelSelectedImportTask = useCallback(async () => {
    if (!selectedImportTaskId) {
      return
    }
    try {
      const payload = await cancelMemoryImportTask(selectedImportTaskId)
      if (!payload.success) {
        throw new Error(payload.error || '取消导入任务失败')
      }
      await refreshImportQueue(true)
      await loadImportTaskDetail(selectedImportTaskId, true)
      toast({
        title: '已请求取消任务',
        description: `任务 ${selectedImportTaskId.slice(0, 12)} 正在取消`,
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : '取消导入任务失败'
      setImportErrorText(message)
      toast({
        title: '取消导入任务失败',
        description: message,
        variant: 'destructive',
      })
    }
  }, [loadImportTaskDetail, refreshImportQueue, selectedImportTaskId, toast])

  const retrySelectedImportTask = useCallback(async () => {
    if (!selectedImportTaskId) {
      return
    }
    try {
      const payload = await retryMemoryImportTask(selectedImportTaskId, {
        overrides: buildCommonImportPayload(),
      })
      if (!payload.success) {
        throw new Error(payload.error || '重试失败项失败')
      }
      const nextTaskId = String(payload.task?.task_id ?? '')
      await refreshImportQueue(true)
      if (nextTaskId) {
        setSelectedImportTaskId(nextTaskId)
        await loadImportTaskDetail(nextTaskId, true)
      } else {
        await loadImportTaskDetail(selectedImportTaskId, true)
      }
      toast({
        title: '重试任务已创建',
        description: nextTaskId ? `重试任务 ${nextTaskId.slice(0, 12)} 已进入队列` : '失败项已提交重试',
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : '重试失败项失败'
      setImportErrorText(message)
      toast({
        title: '重试失败项失败',
        description: message,
        variant: 'destructive',
      })
    }
  }, [buildCommonImportPayload, loadImportTaskDetail, refreshImportQueue, selectedImportTaskId, toast])

  const resolveImportPath = useCallback(async () => {
    if (!pathResolveAlias.trim()) {
      return
    }
    try {
      setResolvingPath(true)
      const payload = await resolveMemoryImportPath({
        alias: pathResolveAlias,
        relative_path: pathResolveRelativePath,
        must_exist: pathResolveMustExist,
      })
      const lines = [
        `路径别名: ${payload.alias}`,
        `相对路径: ${payload.relative_path || '(空)'}`,
        `解析结果: ${payload.resolved_path}`,
        `是否存在: ${String(payload.exists)}`,
        `是否文件: ${String(payload.is_file)}`,
        `是否目录: ${String(payload.is_dir)}`,
      ]
      setPathResolveOutput(lines.join('\n'))
    } catch (error) {
      const message = error instanceof Error ? error.message : '路径解析失败'
      setPathResolveOutput(`解析失败：${message}`)
    } finally {
      setResolvingPath(false)
    }
  }, [pathResolveAlias, pathResolveMustExist, pathResolveRelativePath])

  const selectImportTask = useCallback(
    async (taskId: string) => {
      setSelectedImportTaskId(taskId)
      setImportChunkOffset(0)
      await loadImportTaskDetail(taskId)
    },
    [loadImportTaskDetail],
  )

  const selectImportFile = useCallback(
    async (fileId: string) => {
      if (!selectedImportTaskId) {
        return
      }
      setSelectedImportFileId(fileId)
      setImportChunkOffset(0)
      await loadImportChunks(selectedImportTaskId, fileId, 0)
    },
    [loadImportChunks, selectedImportTaskId],
  )

  const moveImportChunkPage = useCallback(
    async (direction: -1 | 1) => {
      if (!selectedImportTaskId || !selectedImportFileId) {
        return
      }
      const nextOffset =
        direction < 0
          ? Math.max(0, importChunkOffset - IMPORT_CHUNK_PAGE_SIZE)
          : importChunkOffset + IMPORT_CHUNK_PAGE_SIZE
      if (nextOffset === importChunkOffset) {
        return
      }
      setImportChunkOffset(nextOffset)
      await loadImportChunks(selectedImportTaskId, selectedImportFileId, nextOffset)
    },
    [importChunkOffset, loadImportChunks, selectedImportFileId, selectedImportTaskId],
  )

  useEffect(() => {
    if (importAliasKeys.length <= 0) {
      return
    }
    const pickAlias = (current: string, preferred: string): string => {
      if (current && importAliasKeys.includes(current)) {
        return current
      }
      if (importAliasKeys.includes(preferred)) {
        return preferred
      }
      return importAliasKeys[0]
    }
    setRawAlias((current) => pickAlias(current, 'raw'))
    setOpenieAlias((current) => pickAlias(current, 'lpmm'))
    setConvertAlias((current) => pickAlias(current, 'lpmm'))
    setConvertTargetAlias((current) => pickAlias(current, 'plugin_data'))
    setBackfillAlias((current) => pickAlias(current, 'plugin_data'))
    setPathResolveAlias((current) => pickAlias(current, 'raw'))
  }, [importAliasKeys])

  useEffect(() => {
    const defaultFileConcurrency = String(importSettings.default_file_concurrency ?? '').trim()
    const defaultChunkConcurrency = String(importSettings.default_chunk_concurrency ?? '').trim()
    if (defaultFileConcurrency && importCommonFileConcurrency === '2') {
      setImportCommonFileConcurrency(defaultFileConcurrency)
    }
    if (defaultChunkConcurrency && importCommonChunkConcurrency === '4') {
      setImportCommonChunkConcurrency(defaultChunkConcurrency)
    }
  }, [
    importCommonChunkConcurrency,
    importCommonFileConcurrency,
    importSettings.default_chunk_concurrency,
    importSettings.default_file_concurrency,
  ])

  useEffect(() => {
    const defaultSourceDb = String(importSettings.maibot_source_db_default ?? '').trim()
    if (!defaultSourceDb || maibotSourceDbDefaultAppliedRef.current) {
      return
    }
    maibotSourceDbDefaultAppliedRef.current = true
    setMaibotSourceDb((currentSourceDb) => currentSourceDb.trim() ? currentSourceDb : defaultSourceDb)
  }, [importSettings.maibot_source_db_default])

  useEffect(() => {
    if (!selectedImportTaskId && importTasks.length > 0) {
      void selectImportTask(importTasks[0].task_id)
    }
  }, [importTasks, selectImportTask, selectedImportTaskId])

  useEffect(() => {
    if (!selectedImportTaskId) {
      setSelectedImportTask(null)
      setSelectedImportFileId('')
      setImportChunksPayload(null)
      return
    }
    if (!importTasks.some((task) => task.task_id === selectedImportTaskId) && importTasks.length > 0) {
      void selectImportTask(importTasks[0].task_id)
      return
    }
    void loadImportTaskDetail(selectedImportTaskId, true)
  }, [importTasks, loadImportTaskDetail, selectImportTask, selectedImportTaskId])

  useEffect(() => {
    if (!importAutoPolling) {
      return
    }
    const timerId = window.setInterval(() => {
      void refreshImportQueue(true)
      if (selectedImportTaskId) {
        void loadImportTaskDetail(selectedImportTaskId, true)
      }
    }, importPollInterval)
    return () => {
      window.clearInterval(timerId)
    }
  }, [importAutoPolling, importPollInterval, loadImportTaskDetail, refreshImportQueue, selectedImportTaskId])

  // 统一 WebSocket 推送：作为轮询的实时增强；后端未广播时由轮询兜底
  const selectedImportTaskIdRef = useRef<string>('')
  useEffect(() => {
    selectedImportTaskIdRef.current = selectedImportTaskId
  }, [selectedImportTaskId])

  useEffect(() => {
    let cancelled = false
    let unsubscribe: (() => Promise<void>) | undefined
    const handleEvent = (event: MemoryProgressEvent) => {
      if (event.topic === 'import_progress') {
        void refreshImportQueue(true)
        if (selectedImportTaskIdRef.current) {
          void loadImportTaskDetail(selectedImportTaskIdRef.current, true)
        }
      }
    }
    void memoryProgressClient
      .subscribe(handleEvent, ['import_progress'])
      .then((cleanup) => {
        if (cancelled) {
          void cleanup()
          return
        }
        unsubscribe = cleanup
      })
      .catch((error) => {
        // 订阅失败不影响轮询兜底
        console.warn('订阅长期记忆 WebSocket 失败，已退化到轮询兜底', error)
      })
    return () => {
      cancelled = true
      if (unsubscribe) {
        void unsubscribe()
      }
    }
  }, [loadImportTaskDetail, refreshImportQueue])

  const filteredSources = useMemo(() => {
    const keyword = sourceSearch.trim().toLowerCase()
    if (!keyword) {
      return memorySources
    }
    return memorySources.filter((item) => String(item.source ?? '').toLowerCase().includes(keyword))
  }, [memorySources, sourceSearch])

  const filteredDeleteOperations = useMemo(() => {
    const keyword = operationSearch.trim().toLowerCase()
    return deleteOperations.filter((operation) => {
      const mode = String(operation.mode ?? '').trim()
      const status = String(operation.status ?? '').trim()
      const summary = operation.summary ?? {}
      const sources = Array.isArray(summary.sources) ? summary.sources : []

      if (operationModeFilter !== 'all' && mode !== operationModeFilter) {
        return false
      }
      if (operationStatusFilter !== 'all' && status !== operationStatusFilter) {
        return false
      }
      if (!keyword) {
        return true
      }

      return [
        operation.operation_id,
        operation.reason,
        operation.requested_by,
        mode,
        status,
        ...sources.map((item) => String(item)),
      ]
        .map((item) => String(item ?? '').toLowerCase())
        .some((item) => item.includes(keyword))
    })
  }, [deleteOperations, operationModeFilter, operationSearch, operationStatusFilter])

  const deleteOperationPageCount = Math.max(1, Math.ceil(filteredDeleteOperations.length / DELETE_OPERATION_PAGE_SIZE))
  const pagedDeleteOperations = useMemo(() => {
    const start = (operationPage - 1) * DELETE_OPERATION_PAGE_SIZE
    return filteredDeleteOperations.slice(start, start + DELETE_OPERATION_PAGE_SIZE)
  }, [filteredDeleteOperations, operationPage])

  const selectedDeleteOperation = useMemo(
    () => filteredDeleteOperations.find((operation) => operation.operation_id === selectedOperationId) ?? pagedDeleteOperations[0] ?? null,
    [filteredDeleteOperations, pagedDeleteOperations, selectedOperationId],
  )

  useEffect(() => {
    setOperationPage(1)
  }, [operationSearch, operationModeFilter, operationStatusFilter])

  useEffect(() => {
    if (operationPage > deleteOperationPageCount) {
      setOperationPage(deleteOperationPageCount)
    }
  }, [deleteOperationPageCount, operationPage])

  useEffect(() => {
    if (!selectedDeleteOperation) {
      if (selectedOperationId) {
        setSelectedOperationId('')
      }
      setSelectedOperationDetail(null)
      setSelectedOperationDetailError('')
      return
    }
    if (selectedDeleteOperation.operation_id !== selectedOperationId) {
      setSelectedOperationId(selectedDeleteOperation.operation_id)
    }
  }, [selectedDeleteOperation, selectedOperationId])

  useEffect(() => {
    const operationId = selectedDeleteOperation?.operation_id
    if (!operationId) {
      setSelectedOperationDetail(null)
      setSelectedOperationDetailError('')
      return
    }

    let cancelled = false
    setSelectedOperationDetailLoading(true)
    setSelectedOperationDetailError('')

    void getMemoryDeleteOperation(operationId)
      .then((payload) => {
        if (cancelled) {
          return
        }
        if (!payload.success || !payload.operation) {
          setSelectedOperationDetail(null)
          setSelectedOperationDetailError(payload.error || '未能加载删除操作详情')
          return
        }
        setSelectedOperationDetail(payload.operation)
      })
      .catch((error) => {
        if (cancelled) {
          return
        }
        setSelectedOperationDetail(null)
        setSelectedOperationDetailError(error instanceof Error ? error.message : '未能加载删除操作详情')
      })
      .finally(() => {
        if (!cancelled) {
          setSelectedOperationDetailLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [selectedDeleteOperation?.operation_id])

  const toggleSourceSelection = useCallback((source: string, checked: boolean) => {
    setSelectedSources((current) => {
      if (checked) {
        return current.includes(source) ? current : [...current, source]
      }
      return current.filter((item) => item !== source)
    })
  }, [])

  const openSourceDeletePreview = useCallback(async () => {
    if (selectedSources.length <= 0) {
      toast({
        title: '请选择来源',
        description: '至少选择一个来源后再进行删除预览',
        variant: 'destructive',
      })
      return
    }
    const request: MemoryDeleteRequestPayload = {
      mode: 'source',
      selector: { sources: selectedSources },
      reason: 'knowledge_base_source_delete',
      requested_by: 'knowledge_base',
    }
    setDeleteDialogTitle('批量删除来源')
    setDeleteDialogDescription('删除来源只会删除该来源下的段落，以及失去全部证据的关系，不会自动删除实体')
    setPendingDeleteRequest(request)
    setDeletePreview(null)
    setDeleteResult(null)
    setDeletePreviewError(null)
    setDeleteDialogOpen(true)
    setDeletePreviewLoading(true)
    try {
      const preview = await previewMemoryDelete(request)
      setDeletePreview(preview)
    } catch (error) {
      setDeletePreviewError(error instanceof Error ? error.message : '删除预览失败')
    } finally {
      setDeletePreviewLoading(false)
    }
  }, [selectedSources, toast])

  const executePendingDelete = useCallback(async () => {
    if (!pendingDeleteRequest) {
      return
    }
    try {
      setDeleteExecuting(true)
      const result = await executeMemoryDelete(pendingDeleteRequest)
      setDeleteResult(result)
      toast({
        title: result.success ? '删除成功' : '删除失败',
        description: result.success ? `操作 ${result.operation_id} 已完成` : result.error || '未能执行删除',
        variant: result.success ? 'default' : 'destructive',
      })
      if (result.success) {
        const [sourcePayload, deleteOperationPayload] = await Promise.all([
          getMemorySources(),
          getMemoryDeleteOperations(DELETE_OPERATION_FETCH_LIMIT),
        ])
        setMemorySources(sourcePayload.items ?? [])
        setDeleteOperations(deleteOperationPayload.items ?? [])
        setSelectedSources([])
      }
    } catch (error) {
      setDeletePreviewError(error instanceof Error ? error.message : '删除失败')
      toast({
        title: '删除失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setDeleteExecuting(false)
    }
  }, [pendingDeleteRequest, toast])

  const restoreDeleteOperation = useCallback(async (operationId: string) => {
    try {
      setDeleteRestoring(true)
      await restoreMemoryDelete({ operation_id: operationId, requested_by: 'knowledge_base' })
      toast({
        title: '恢复成功',
        description: `删除操作 ${operationId} 已恢复`,
      })
      setDeleteDialogOpen(false)
      const [sourcePayload, deleteOperationPayload] = await Promise.all([
        getMemorySources(),
        getMemoryDeleteOperations(DELETE_OPERATION_FETCH_LIMIT),
      ])
      setMemorySources(sourcePayload.items ?? [])
      setDeleteOperations(deleteOperationPayload.items ?? [])
    } catch (error) {
      toast({
        title: '恢复失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setDeleteRestoring(false)
    }
  }, [toast])

  const closeDeleteDialog = useCallback((open: boolean) => {
    if (!open) {
      setDeleteDialogOpen(false)
      setDeletePreview(null)
      setDeleteResult(null)
      setDeletePreviewError(null)
      setPendingDeleteRequest(null)
      return
    }
    setDeleteDialogOpen(true)
  }, [])

  const filteredFeedbackCorrections = useMemo(() => {
    const keyword = feedbackSearch.trim().toLowerCase()
    return feedbackCorrections.filter((item) => {
      const taskStatus = String(item.task_status ?? '').trim().toLowerCase()
      const rollbackStatus = String(item.rollback_status ?? '').trim().toLowerCase()
      if (feedbackStatusFilter !== 'all' && taskStatus !== feedbackStatusFilter) {
        return false
      }
      if (feedbackRollbackFilter !== 'all' && rollbackStatus !== feedbackRollbackFilter) {
        return false
      }
      if (!keyword) {
        return true
      }
      return [
        item.query_tool_id,
        item.session_id,
        item.query_text,
        item.decision,
        item.task_status,
        item.rollback_status,
      ]
        .map((value) => String(value ?? '').toLowerCase())
        .some((value) => value.includes(keyword))
    })
  }, [feedbackCorrections, feedbackRollbackFilter, feedbackSearch, feedbackStatusFilter])

  const feedbackPageCount = Math.max(1, Math.ceil(filteredFeedbackCorrections.length / FEEDBACK_CORRECTION_PAGE_SIZE))
  const pagedFeedbackCorrections = useMemo(() => {
    const start = (feedbackPage - 1) * FEEDBACK_CORRECTION_PAGE_SIZE
    return filteredFeedbackCorrections.slice(start, start + FEEDBACK_CORRECTION_PAGE_SIZE)
  }, [feedbackPage, filteredFeedbackCorrections])

  const selectedFeedbackCorrection = useMemo(
    () =>
      filteredFeedbackCorrections.find((item) => item.task_id === selectedFeedbackTaskId)
      ?? pagedFeedbackCorrections[0]
      ?? null,
    [filteredFeedbackCorrections, pagedFeedbackCorrections, selectedFeedbackTaskId],
  )

  useEffect(() => {
    setFeedbackPage(1)
  }, [feedbackSearch, feedbackStatusFilter, feedbackRollbackFilter])

  useEffect(() => {
    if (feedbackPage > feedbackPageCount) {
      setFeedbackPage(feedbackPageCount)
    }
  }, [feedbackPage, feedbackPageCount])

  useEffect(() => {
    if (!selectedFeedbackCorrection) {
      if (selectedFeedbackTaskId) {
        setSelectedFeedbackTaskId(0)
      }
      setSelectedFeedbackTaskDetail(null)
      setSelectedFeedbackTaskError('')
      return
    }
    if (selectedFeedbackCorrection.task_id !== selectedFeedbackTaskId) {
      setSelectedFeedbackTaskId(selectedFeedbackCorrection.task_id)
    }
  }, [selectedFeedbackCorrection, selectedFeedbackTaskId])

  useEffect(() => {
    const taskId = selectedFeedbackCorrection?.task_id
    if (!taskId) {
      setSelectedFeedbackTaskDetail(null)
      setSelectedFeedbackTaskError('')
      return
    }

    let cancelled = false
    setSelectedFeedbackTaskLoading(true)
    setSelectedFeedbackTaskError('')

    void getMemoryFeedbackCorrection(taskId)
      .then((payload) => {
        if (cancelled) {
          return
        }
        if (!payload.success || !payload.task) {
          setSelectedFeedbackTaskDetail(null)
          setSelectedFeedbackTaskError(payload.error || '未能加载纠错任务详情')
          return
        }
        setSelectedFeedbackTaskDetail(payload.task)
      })
      .catch((error) => {
        if (cancelled) {
          return
        }
        setSelectedFeedbackTaskDetail(null)
        setSelectedFeedbackTaskError(error instanceof Error ? error.message : '未能加载纠错任务详情')
      })
      .finally(() => {
        if (!cancelled) {
          setSelectedFeedbackTaskLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [selectedFeedbackCorrection?.task_id])

  const selectedFeedbackResolved = useMemo<MemoryFeedbackCorrectionDetailTaskPayload | null>(() => {
    if (!selectedFeedbackCorrection) {
      return null
    }
    if (selectedFeedbackTaskDetail?.task_id === selectedFeedbackCorrection.task_id) {
      return {
        ...selectedFeedbackCorrection,
        ...selectedFeedbackTaskDetail,
      } satisfies MemoryFeedbackCorrectionDetailTaskPayload
    }
    return selectedFeedbackTaskDetail ?? selectedFeedbackCorrection
  }, [selectedFeedbackCorrection, selectedFeedbackTaskDetail])
  const selectedFeedbackPreview = useMemo(
    () => getFeedbackCorrectionPreview(selectedFeedbackResolved),
    [selectedFeedbackResolved],
  )
  const selectedFeedbackImpactSummary = useMemo(
    () => buildFeedbackImpactSummary(selectedFeedbackResolved),
    [selectedFeedbackResolved],
  )

  const selectedFeedbackActionLogs: MemoryFeedbackActionLogPayload[] = Array.isArray(selectedFeedbackResolved?.action_logs)
    ? selectedFeedbackResolved.action_logs
    : []
  const filteredFeedbackActionLogs = useMemo(() => {
    const keyword = feedbackActionLogSearch.trim().toLowerCase()
    if (!keyword) {
      return selectedFeedbackActionLogs
    }
    return selectedFeedbackActionLogs.filter((item) =>
      [
        item.action_type,
        item.target_hash,
        item.reason,
        summarizeFeedbackActionPayload(item.before_payload),
        summarizeFeedbackActionPayload(item.after_payload),
      ]
        .map((value) => String(value ?? '').toLowerCase())
        .some((value) => value.includes(keyword)),
    )
  }, [feedbackActionLogSearch, selectedFeedbackActionLogs])
  const feedbackActionLogPageCount = Math.max(
    1,
    Math.ceil(filteredFeedbackActionLogs.length / FEEDBACK_ACTION_LOG_PAGE_SIZE),
  )
  const pagedFeedbackActionLogs = useMemo(() => {
    const start = (feedbackActionLogPage - 1) * FEEDBACK_ACTION_LOG_PAGE_SIZE
    return filteredFeedbackActionLogs.slice(start, start + FEEDBACK_ACTION_LOG_PAGE_SIZE)
  }, [feedbackActionLogPage, filteredFeedbackActionLogs])

  useEffect(() => {
    setFeedbackActionLogPage(1)
  }, [selectedFeedbackTaskId, feedbackActionLogSearch])

  useEffect(() => {
    if (feedbackActionLogPage > feedbackActionLogPageCount) {
      setFeedbackActionLogPage(feedbackActionLogPageCount)
    }
  }, [feedbackActionLogPage, feedbackActionLogPageCount])

  const openFeedbackRollbackDialog = useCallback(() => {
    setFeedbackRollbackReason('')
    setFeedbackRollbackDialogOpen(true)
  }, [])

  const executeFeedbackRollback = useCallback(async () => {
    const taskId = selectedFeedbackResolved?.task_id
    if (!taskId) {
      return
    }
    try {
      setFeedbackRollingBack(true)
      const payload = await rollbackMemoryFeedbackCorrection(taskId, {
        requested_by: 'knowledge_base',
        reason: feedbackRollbackReason.trim(),
      })
      if (!payload.success) {
        throw new Error(payload.error || '回退失败')
      }
      toast({
        title: payload.already_rolled_back ? '该纠错已回退' : '纠错回退成功',
        description: `任务 ${taskId} 的回退结果已写入日志`,
      })
      setFeedbackRollbackDialogOpen(false)
      const [listPayload, detailPayload] = await Promise.all([
        getMemoryFeedbackCorrections({ limit: FEEDBACK_CORRECTION_FETCH_LIMIT }),
        getMemoryFeedbackCorrection(taskId),
      ])
      setFeedbackCorrections(listPayload.items ?? [])
      setSelectedFeedbackTaskDetail(detailPayload.task ?? null)
      const [sourcePayload, runtimePayload] = await Promise.all([
        getMemorySources(),
        getMemoryRuntimeConfig(),
      ])
      setMemorySources(sourcePayload.items ?? [])
      setRuntimeConfig(runtimePayload)
    } catch (error) {
      toast({
        title: '纠错回退失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setFeedbackRollingBack(false)
    }
  }, [feedbackRollbackReason, selectedFeedbackResolved?.task_id, toast])

  const selectedOperationResolved = useMemo(() => {
    if (!selectedDeleteOperation) {
      return null
    }
    if (selectedOperationDetail?.operation_id === selectedDeleteOperation.operation_id) {
      return {
        ...selectedDeleteOperation,
        ...selectedOperationDetail,
      } satisfies MemoryDeleteOperationPayload
    }
    return selectedDeleteOperation
  }, [selectedDeleteOperation, selectedOperationDetail])
  const selectedOperationSummaryResolved = ((selectedOperationResolved?.summary ?? {}) as Record<string, unknown>)
  const selectedOperationCounts = ((selectedOperationSummaryResolved.counts as Record<string, number> | undefined) ?? {})
  const selectedOperationSources = Array.isArray(selectedOperationSummaryResolved.sources)
    ? selectedOperationSummaryResolved.sources.map((item) => String(item)).filter(Boolean)
    : []
  const selectedOperationItems = Array.isArray(selectedOperationResolved?.items)
    ? selectedOperationResolved.items
    : []
  const filteredSelectedOperationItems = useMemo(() => {
    const keyword = selectedOperationItemSearch.trim().toLowerCase()
    if (!keyword) {
      return selectedOperationItems
    }
    return selectedOperationItems.filter((item) => {
      const payload = item.payload ?? {}
      const source = String(payload.source ?? '').trim()
      return [
        item.item_type,
        item.item_hash,
        item.item_key,
        source,
      ]
        .map((value) => String(value ?? '').toLowerCase())
        .some((value) => value.includes(keyword))
    })
  }, [selectedOperationItemSearch, selectedOperationItems])
  const selectedOperationItemPageCount = Math.max(
    1,
    Math.ceil(filteredSelectedOperationItems.length / DELETE_OPERATION_ITEM_PAGE_SIZE),
  )
  const pagedSelectedOperationItems = useMemo(() => {
    const start = (selectedOperationItemPage - 1) * DELETE_OPERATION_ITEM_PAGE_SIZE
    return filteredSelectedOperationItems.slice(start, start + DELETE_OPERATION_ITEM_PAGE_SIZE)
  }, [filteredSelectedOperationItems, selectedOperationItemPage])

  useEffect(() => {
    setSelectedOperationItemPage(1)
  }, [selectedOperationId, selectedOperationItemSearch])

  useEffect(() => {
    if (selectedOperationItemPage > selectedOperationItemPageCount) {
      setSelectedOperationItemPage(selectedOperationItemPageCount)
    }
  }, [selectedOperationItemPage, selectedOperationItemPageCount])

  const refreshSelfCheck = useCallback(async () => {
    try {
      setRefreshingCheck(true)
      const payload = await refreshMemoryRuntimeSelfCheck()
      setSelfCheckReport((payload.report ?? null) as Record<string, unknown> | null)
      const nextRuntime = await getMemoryRuntimeConfig()
      setRuntimeConfig(nextRuntime)
      toast({
        title: payload.success ? '自检通过' : '自检未通过',
        description: payload.success ? '运行时状态正常' : '请检查 embedding 配置和外部服务连通性',
        variant: payload.success ? 'default' : 'destructive',
      })
    } catch (error) {
      toast({
        title: '运行时自检失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setRefreshingCheck(false)
    }
  }, [toast])

  const submitImportByMode = useCallback(async () => {
    if (creatingImport) {
      return
    }
    switch (importCreateMode) {
      case 'upload':
        await submitUploadImport()
        break
      case 'paste':
        await submitPasteImport()
        break
      case 'raw_scan':
        await submitRawScanImport()
        break
      case 'lpmm_openie':
        await submitOpenieImport()
        break
      case 'lpmm_convert':
        await submitConvertImport()
        break
      case 'temporal_backfill':
        await submitBackfillImport()
        break
      case 'maibot_migration':
        await submitMaibotMigrationImport()
        break
      default:
        break
    }
  }, [
    creatingImport,
    importCreateMode,
    submitBackfillImport,
    submitConvertImport,
    submitMaibotMigrationImport,
    submitOpenieImport,
    submitPasteImport,
    submitRawScanImport,
    submitUploadImport,
  ])

  const submitTuningTask = useCallback(async () => {
    try {
      setCreatingTuning(true)
      await createMemoryTuningTask({
        objective: tuningObjective,
        intensity: tuningIntensity,
        sample_size: Number(tuningSampleSize),
        top_k_eval: Number(tuningTopKEval),
      })
      const tasks = await getMemoryTuningTasks(20)
      setTuningTasks(tasks.items ?? [])
      toast({ title: '调优任务已创建', description: '新的检索调优任务已经进入队列' })
    } catch (error) {
      toast({
        title: '创建调优任务失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    } finally {
      setCreatingTuning(false)
    }
  }, [toast, tuningIntensity, tuningObjective, tuningSampleSize, tuningTopKEval])

  const applyBestTask = useCallback(async (taskId: string) => {
    try {
      await applyBestMemoryTuningProfile(taskId)
      const [profilePayload, runtimePayload, tuningTaskPayload] = await Promise.all([
        getMemoryTuningProfile(),
        getMemoryRuntimeConfig(),
        getMemoryTuningTasks(20),
      ])
      setTuningProfile(profilePayload.profile ?? {})
      setTuningProfileToml(profilePayload.toml ?? '')
      setRuntimeConfig(runtimePayload)
      setTuningTasks(tuningTaskPayload.items ?? [])
      toast({ title: '最佳参数已应用', description: `任务 ${taskId} 的最佳轮次已经写入运行时` })
    } catch (error) {
      toast({
        title: '应用最佳参数失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive',
      })
    }
  }, [toast])

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="rounded-xl border bg-background px-6 py-5 text-sm text-muted-foreground shadow-sm">
          正在加载长期记忆控制台...
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-gradient-to-b from-background via-background to-muted/15">
      <div className="flex-none border-b bg-card/70 px-6 py-4 backdrop-blur">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-primary/80">
              A_Memorix
            </div>
            <h1 className="mt-1 text-2xl font-bold leading-tight">长期记忆控制台</h1>
            <p className="mt-1 text-sm text-muted-foreground">
                      在这里完成自检、导入资料和检索调优——一站式管理记忆库
            </p>
          </div>

          <div className="hidden">
            <Button variant="outline" size="sm" onClick={() => setActiveTab('graph')}>
              <Database className="mr-2 h-4 w-4" />
              打开图谱
            </Button>
            <Button variant="outline" size="sm" onClick={() => void loadPage()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              刷新数据
            </Button>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-[1800px] flex-col gap-6 px-6 py-6">
          <div className="hidden">
            <Button variant="outline" size="sm" onClick={() => void loadPage()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              刷新数据
            </Button>
          </div>
          {/* 运行时状态条 —— 紧凑、常驻、一眼看完 */}
          {runtimeBadges.length > 0 ? (
            <div className="rounded-2xl border border-border/60 bg-card/60 p-4 shadow-sm backdrop-blur">
              <div className="mb-3 flex items-center gap-2">
                <div className="mr-auto flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  <Gauge className="h-3.5 w-3.5" />
                  运行时状态
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => void loadPage()}
                >
                  <RefreshCw className="mr-1.5 h-3 w-3" />
                  刷新数据
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => void refreshSelfCheck()}
                  disabled={refreshingCheck}
                >
                  <RefreshCw className={cn('mr-1.5 h-3 w-3', refreshingCheck && 'animate-spin')} />
                  自检
                </Button>
              </div>
              <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
                {runtimeBadges.map((item) => (
                  <div
                    key={item.label}
                    className={cn(
                      'flex items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors',
                      item.className,
                    )}
                  >
                    <div className="flex-none rounded-lg border bg-background/70 p-1.5 shadow-sm">
                      <item.icon className={cn('h-4 w-4', item.iconClassName)} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-[11px] font-medium text-muted-foreground">{item.label}</div>
                      <div className="truncate text-sm font-semibold leading-snug" title={item.value}>
                        {item.value}
                      </div>
                      <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                        {item.description}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* 快速开始 Hero —— 给新用户明确的"先做什么" */}
          <div className="overflow-hidden rounded-2xl border border-primary/20 bg-gradient-to-br from-primary/10 via-primary/5 to-transparent p-5 shadow-sm">
            <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
              <div className="space-y-1.5 lg:max-w-sm">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-primary">
                  快速开始
                </div>
                <h2 className="text-lg font-semibold leading-tight">先从这三件事入手</h2>
                <p className="text-sm text-muted-foreground">
                  不知道该做什么？挑一个最常用的入口，下面的标签页里有更详细的设置。
                </p>
              </div>
              <div className="grid w-full gap-2.5 sm:grid-cols-3 lg:max-w-3xl">
                <button
                  type="button"
                  onClick={() => setActiveTab('import')}
                  className="group flex items-start gap-3 rounded-xl border border-border/70 bg-background/80 p-3.5 text-left transition hover:border-primary/50 hover:bg-background hover:shadow-md"
                >
                  <div className="flex-none rounded-lg bg-primary/10 p-2 text-primary transition-transform group-hover:scale-105">
                    <Upload className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold">导入资料</div>
                    <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                      把文件、聊天记录写进记忆库
                    </div>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('tuning')}
                  className="group flex items-start gap-3 rounded-xl border border-border/70 bg-background/80 p-3.5 text-left transition hover:border-primary/50 hover:bg-background hover:shadow-md"
                >
                  <div className="flex-none rounded-lg bg-amber-500/10 p-2 text-amber-500 transition-transform group-hover:scale-105">
                    <SlidersHorizontal className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold">检索调优</div>
                    <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                      让回忆变得更准、更聪明
                    </div>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('graph')}
                  className="group flex items-start gap-3 rounded-xl border border-border/70 bg-background/80 p-3.5 text-left transition hover:border-primary/50 hover:bg-background hover:shadow-md"
                >
                  <div className="flex-none rounded-lg bg-violet-500/10 p-2 text-violet-500 transition-transform group-hover:scale-105">
                    <Database className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold">打开图谱</div>
                    <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                      可视化已存的实体和关系
                    </div>
                  </div>
                </button>
              </div>
            </div>
          </div>

          <Tabs
            value={activeTab}
            onValueChange={(value) => setActiveTab(value as typeof activeTab)}
            className="space-y-5"
          >
            <div className="sticky top-0 z-10 -mx-6 border-b border-border/40 bg-background/85 px-6 pb-2 pt-1 backdrop-blur supports-[backdrop-filter]:bg-background/70">
              <MemoryMiniTabs
                items={[
                  { value: 'overview', label: '概览', description: '运行状态与运行时摘要' },
                  { value: 'graph', label: '图谱', description: '实体关系图与证据视图' },
                  { value: 'import', label: '导入', description: '创建并管理导入任务' },
                  { value: 'tuning', label: '调优', description: '检索策略调优' },
                  { value: 'episodes', label: '情景记忆', description: '查看和重建情景记忆' },
                  { value: 'profiles', label: '人物画像', description: '查询和维护人物画像' },
                  { value: 'maintenance', label: '维护', description: '回收站与记忆状态维护' },
                  { value: 'delete', label: '删除', description: '批量删除与历史回溯' },
                  { value: 'feedback', label: '纠错历史', description: '查看反馈与回滚' },
                ]}
                triggerClassName="px-4"
              />
            </div>

            <TabsContent value="graph" className="h-[calc(100vh-220px)] min-h-[720px] overflow-hidden rounded-2xl border border-border/60 bg-background shadow-sm">
              <KnowledgeGraphPage embedded onOpenConsole={() => setActiveTab('overview')} />
            </TabsContent>

            <TabsContent value="overview" className="space-y-4">
              <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
                <Card>
                  <CardHeader className="flex flex-row items-start justify-between space-y-0">
                    <div>
                      <CardTitle className="flex items-center gap-2">
                        <Gauge className="h-4 w-4" />
                        运行时自检
                      </CardTitle>
                      <CardDescription>用于确认 embedding、向量库与运行时状态是否一致</CardDescription>
                    </div>
                    <Button size="sm" onClick={() => void refreshSelfCheck()} disabled={refreshingCheck}>
                      <RefreshCw className={`mr-2 h-4 w-4 ${refreshingCheck ? 'animate-spin' : ''}`} />
                      重新自检
                    </Button>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <Alert>
                      <AlertDescription>
                        长期记忆配置已移动到主程序配置，请在“主程序配置 / 长期记忆”中调整。
                      </AlertDescription>
                    </Alert>
                    <CodeEditor
                      value={JSON.stringify(selfCheckReport ?? runtimeConfig ?? {}, null, 2)}
                      language="json"
                      readOnly
                      height="320px"
                    />
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Sparkles className="h-4 w-4" />
                      关键指标
                    </CardTitle>
                    <CardDescription>用于快速判断是否需要补回向量或重新调优</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4 text-sm">
                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="rounded-lg border bg-muted/30 p-3">
                        <div className="text-xs text-muted-foreground">待补回段落向量</div>
                        <div className="mt-1 text-2xl font-semibold">{runtimeConfig?.paragraph_vector_backfill_pending ?? 0}</div>
                      </div>
                      <div className="rounded-lg border bg-muted/30 p-3">
                        <div className="text-xs text-muted-foreground">失败补回任务</div>
                        <div className="mt-1 text-2xl font-semibold">{runtimeConfig?.paragraph_vector_backfill_failed ?? 0}</div>
                      </div>
                    </div>
                    <details className="rounded-lg border bg-muted/30 p-3" open>
                      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">当前调优配置</summary>
                      <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs">
                        {JSON.stringify(tuningProfile, null, 2)}
                      </pre>
                    </details>
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            <ImportTab
              importCreateMode={importCreateMode}
              setImportCreateMode={setImportCreateMode}
              importSettings={importSettings}
              importCommonFileConcurrency={importCommonFileConcurrency}
              setImportCommonFileConcurrency={setImportCommonFileConcurrency}
              importCommonChunkConcurrency={importCommonChunkConcurrency}
              setImportCommonChunkConcurrency={setImportCommonChunkConcurrency}
              importCommonLlmEnabled={importCommonLlmEnabled}
              setImportCommonLlmEnabled={setImportCommonLlmEnabled}
              importCommonChatLog={importCommonChatLog}
              setImportCommonChatLog={setImportCommonChatLog}
              importCommonStrategyOverride={importCommonStrategyOverride}
              setImportCommonStrategyOverride={setImportCommonStrategyOverride}
              importCommonDedupePolicy={importCommonDedupePolicy}
              setImportCommonDedupePolicy={setImportCommonDedupePolicy}
              importCommonChatReferenceTime={importCommonChatReferenceTime}
              setImportCommonChatReferenceTime={setImportCommonChatReferenceTime}
              importCommonForce={importCommonForce}
              setImportCommonForce={setImportCommonForce}
              importCommonClearManifest={importCommonClearManifest}
              setImportCommonClearManifest={setImportCommonClearManifest}
              uploadInputMode={uploadInputMode}
              setUploadInputMode={setUploadInputMode}
              uploadFiles={uploadFiles}
              setUploadFiles={setUploadFiles}
              pasteName={pasteName}
              setPasteName={setPasteName}
              pasteMode={pasteMode}
              setPasteMode={setPasteMode}
              pasteContent={pasteContent}
              setPasteContent={setPasteContent}
              rawAlias={rawAlias}
              setRawAlias={setRawAlias}
              rawInputMode={rawInputMode}
              setRawInputMode={setRawInputMode}
              rawRelativePath={rawRelativePath}
              setRawRelativePath={setRawRelativePath}
              rawGlob={rawGlob}
              setRawGlob={setRawGlob}
              rawRecursive={rawRecursive}
              setRawRecursive={setRawRecursive}
              openieAlias={openieAlias}
              setOpenieAlias={setOpenieAlias}
              openieRelativePath={openieRelativePath}
              setOpenieRelativePath={setOpenieRelativePath}
              openieIncludeAllJson={openieIncludeAllJson}
              setOpenieIncludeAllJson={setOpenieIncludeAllJson}
              convertAlias={convertAlias}
              setConvertAlias={setConvertAlias}
              convertTargetAlias={convertTargetAlias}
              setConvertTargetAlias={setConvertTargetAlias}
              convertRelativePath={convertRelativePath}
              setConvertRelativePath={setConvertRelativePath}
              convertTargetRelativePath={convertTargetRelativePath}
              setConvertTargetRelativePath={setConvertTargetRelativePath}
              convertDimension={convertDimension}
              setConvertDimension={setConvertDimension}
              convertBatchSize={convertBatchSize}
              setConvertBatchSize={setConvertBatchSize}
              backfillAlias={backfillAlias}
              setBackfillAlias={setBackfillAlias}
              backfillLimit={backfillLimit}
              setBackfillLimit={setBackfillLimit}
              backfillRelativePath={backfillRelativePath}
              setBackfillRelativePath={setBackfillRelativePath}
              backfillDryRun={backfillDryRun}
              setBackfillDryRun={setBackfillDryRun}
              backfillNoCreatedFallback={backfillNoCreatedFallback}
              setBackfillNoCreatedFallback={setBackfillNoCreatedFallback}
              maibotSourceDb={maibotSourceDb}
              setMaibotSourceDb={setMaibotSourceDb}
              maibotTimeFrom={maibotTimeFrom}
              setMaibotTimeFrom={setMaibotTimeFrom}
              maibotTimeTo={maibotTimeTo}
              setMaibotTimeTo={setMaibotTimeTo}
              maibotStartId={maibotStartId}
              setMaibotStartId={setMaibotStartId}
              maibotEndId={maibotEndId}
              setMaibotEndId={setMaibotEndId}
              maibotStreamIds={maibotStreamIds}
              setMaibotStreamIds={setMaibotStreamIds}
              maibotGroupIds={maibotGroupIds}
              setMaibotGroupIds={setMaibotGroupIds}
              maibotUserIds={maibotUserIds}
              setMaibotUserIds={setMaibotUserIds}
              maibotReadBatchSize={maibotReadBatchSize}
              setMaibotReadBatchSize={setMaibotReadBatchSize}
              maibotCommitWindowRows={maibotCommitWindowRows}
              setMaibotCommitWindowRows={setMaibotCommitWindowRows}
              maibotEmbedWorkers={maibotEmbedWorkers}
              setMaibotEmbedWorkers={setMaibotEmbedWorkers}
              maibotNoResume={maibotNoResume}
              setMaibotNoResume={setMaibotNoResume}
              maibotResetState={maibotResetState}
              setMaibotResetState={setMaibotResetState}
              maibotDryRun={maibotDryRun}
              setMaibotDryRun={setMaibotDryRun}
              maibotVerifyOnly={maibotVerifyOnly}
              setMaibotVerifyOnly={setMaibotVerifyOnly}
              submitImportByMode={submitImportByMode}
              creatingImport={creatingImport}
              pathResolveAlias={pathResolveAlias}
              setPathResolveAlias={setPathResolveAlias}
              importAliasKeys={importAliasKeys}
              pathResolveRelativePath={pathResolveRelativePath}
              setPathResolveRelativePath={setPathResolveRelativePath}
              pathResolveMustExist={pathResolveMustExist}
              setPathResolveMustExist={setPathResolveMustExist}
              resolveImportPath={resolveImportPath}
              resolvingPath={resolvingPath}
              pathResolveOutput={pathResolveOutput}
              refreshImportQueue={refreshImportQueue}
              runningImportTasks={runningImportTasks}
              queuedImportTasks={queuedImportTasks}
              recentImportTasks={recentImportTasks}
              selectedImportTaskId={selectedImportTaskId}
              selectImportTask={selectImportTask}
              importAutoPolling={importAutoPolling}
              setImportAutoPolling={setImportAutoPolling}
              importPollInterval={importPollInterval}
              importErrorText={importErrorText}
              cancelSelectedImportTask={cancelSelectedImportTask}
              retrySelectedImportTask={retrySelectedImportTask}
              selectedImportTaskLoading={selectedImportTaskLoading}
              selectedImportTaskResolved={selectedImportTaskResolved}
              selectedImportRetrySummary={selectedImportRetrySummary}
              selectedImportTaskErrorText={selectedImportTaskErrorText}
              selectedImportFiles={selectedImportFiles}
              selectedImportFileId={selectedImportFileId}
              selectImportFile={selectImportFile}
              importChunkTotal={importChunkTotal}
              importChunkOffset={importChunkOffset}
              moveImportChunkPage={moveImportChunkPage}
              canImportChunkPrev={canImportChunkPrev}
              canImportChunkNext={canImportChunkNext}
              importChunksLoading={importChunksLoading}
              selectedImportChunks={selectedImportChunks}
            />

            <TuningTab
              tuningObjective={tuningObjective}
              setTuningObjective={setTuningObjective}
              tuningIntensity={tuningIntensity}
              setTuningIntensity={setTuningIntensity}
              tuningSampleSize={tuningSampleSize}
              setTuningSampleSize={setTuningSampleSize}
              tuningTopKEval={tuningTopKEval}
              setTuningTopKEval={setTuningTopKEval}
              submitTuningTask={submitTuningTask}
              creatingTuning={creatingTuning}
              tuningProfile={tuningProfile}
              tuningProfileToml={tuningProfileToml}
              tuningTasks={tuningTasks}
              applyBestTask={applyBestTask}
            />

            <TabsContent value="episodes" className="space-y-4">
              {visitedMemoryTabs.has('episodes') ? <MemoryEpisodeManager /> : null}
            </TabsContent>

            <TabsContent value="profiles" className="space-y-4">
              {visitedMemoryTabs.has('profiles') ? <MemoryProfileManager /> : null}
            </TabsContent>

            <TabsContent value="maintenance" className="space-y-4">
              {visitedMemoryTabs.has('maintenance') ? <MemoryMaintenanceManager /> : null}
            </TabsContent>

            <DeleteTab
              sourceSearch={sourceSearch}
              setSourceSearch={setSourceSearch}
              selectedSources={selectedSources}
              setSelectedSources={setSelectedSources}
              filteredSources={filteredSources}
              openSourceDeletePreview={openSourceDeletePreview}
              toggleSourceSelection={toggleSourceSelection}
              operationSearch={operationSearch}
              setOperationSearch={setOperationSearch}
              operationModeFilter={operationModeFilter}
              setOperationModeFilter={setOperationModeFilter}
              operationStatusFilter={operationStatusFilter}
              setOperationStatusFilter={setOperationStatusFilter}
              filteredDeleteOperations={filteredDeleteOperations}
              deleteOperations={deleteOperations}
              operationPage={operationPage}
              setOperationPage={setOperationPage}
              deleteOperationPageCount={deleteOperationPageCount}
              pagedDeleteOperations={pagedDeleteOperations}
              selectedDeleteOperation={selectedDeleteOperation}
              setSelectedOperationId={setSelectedOperationId}
              restoreDeleteOperation={restoreDeleteOperation}
              deleteRestoring={deleteRestoring}
              selectedOperationCounts={selectedOperationCounts}
              selectedOperationDetailLoading={selectedOperationDetailLoading}
              selectedOperationDetailError={selectedOperationDetailError}
              selectedOperationSources={selectedOperationSources}
              selectedOperationItems={selectedOperationItems}
              filteredSelectedOperationItems={filteredSelectedOperationItems}
              selectedOperationItemSearch={selectedOperationItemSearch}
              setSelectedOperationItemSearch={setSelectedOperationItemSearch}
              selectedOperationItemPage={selectedOperationItemPage}
              setSelectedOperationItemPage={setSelectedOperationItemPage}
              selectedOperationItemPageCount={selectedOperationItemPageCount}
              pagedSelectedOperationItems={pagedSelectedOperationItems}
            />

            <FeedbackTab
              feedbackSearch={feedbackSearch}
              setFeedbackSearch={setFeedbackSearch}
              feedbackStatusFilter={feedbackStatusFilter}
              setFeedbackStatusFilter={setFeedbackStatusFilter}
              feedbackRollbackFilter={feedbackRollbackFilter}
              setFeedbackRollbackFilter={setFeedbackRollbackFilter}
              filteredFeedbackCorrections={filteredFeedbackCorrections}
              feedbackCorrections={feedbackCorrections}
              pagedFeedbackCorrections={pagedFeedbackCorrections}
              feedbackPage={feedbackPage}
              setFeedbackPage={setFeedbackPage}
              feedbackPageCount={feedbackPageCount}
              selectedFeedbackCorrection={selectedFeedbackCorrection}
              setSelectedFeedbackTaskId={setSelectedFeedbackTaskId}
              selectedFeedbackResolved={selectedFeedbackResolved}
              selectedFeedbackPreview={selectedFeedbackPreview}
              selectedFeedbackImpactSummary={selectedFeedbackImpactSummary}
              openFeedbackRollbackDialog={openFeedbackRollbackDialog}
              feedbackRollingBack={feedbackRollingBack}
              selectedFeedbackTaskLoading={selectedFeedbackTaskLoading}
              selectedFeedbackTaskError={selectedFeedbackTaskError}
              feedbackActionLogPage={feedbackActionLogPage}
              setFeedbackActionLogPage={setFeedbackActionLogPage}
              feedbackActionLogPageCount={feedbackActionLogPageCount}
              feedbackActionLogSearch={feedbackActionLogSearch}
              setFeedbackActionLogSearch={setFeedbackActionLogSearch}
              pagedFeedbackActionLogs={pagedFeedbackActionLogs}
              selectedFeedbackActionLogs={selectedFeedbackActionLogs}
            />
          </Tabs>
        </div>
      </div>

      <MemoryDeleteDialog
        open={deleteDialogOpen}
        onOpenChange={closeDeleteDialog}
        title={deleteDialogTitle}
        description={deleteDialogDescription}
        preview={deletePreview}
        result={deleteResult}
        loadingPreview={deletePreviewLoading}
        executing={deleteExecuting}
        restoring={deleteRestoring}
        error={deletePreviewError}
        onExecute={() => void executePendingDelete()}
        onRestore={() => void (deleteResult?.operation_id ? restoreDeleteOperation(deleteResult.operation_id) : Promise.resolve())}
      />

      <Dialog open={feedbackRollbackDialogOpen} onOpenChange={setFeedbackRollbackDialogOpen}>
        <DialogContent className="max-w-lg" confirmOnEnter>
          <DialogHeader>
            <DialogTitle>回退本次纠错</DialogTitle>
            <DialogDescription>
              这会恢复旧关系状态、隐藏本次纠错写入的段落，并重新触发 Episode / Profile 的异步修复。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border bg-muted/20 p-3 text-sm">
              <div className="font-medium break-words">{selectedFeedbackResolved?.query_text || '无查询文本'}</div>
              <div className="mt-1 font-mono text-[11px] break-all text-muted-foreground">
                {selectedFeedbackResolved?.query_tool_id}
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="feedback-rollback-reason">回退原因</Label>
              <Textarea
                id="feedback-rollback-reason"
                value={feedbackRollbackReason}
                onChange={(event) => setFeedbackRollbackReason(event.target.value)}
                placeholder="可选，建议填写本次人工回退原因"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFeedbackRollbackDialogOpen(false)} disabled={feedbackRollingBack}>
              取消
            </Button>
            <Button onClick={() => void executeFeedbackRollback()} disabled={feedbackRollingBack}>
              {feedbackRollingBack ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  回退中
                </>
              ) : (
                <>
                  <RotateCcw className="mr-2 h-4 w-4" />
                  确认回退
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
