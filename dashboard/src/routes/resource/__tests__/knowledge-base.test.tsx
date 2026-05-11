import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { KnowledgeBasePage } from '../knowledge-base'
import * as memoryApi from '@/lib/memory-api'

const navigateMock = vi.fn()
const toastMock = vi.fn()

afterEach(() => {
  cleanup()
})

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => navigateMock,
}))

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: toastMock }),
}))

vi.mock('@/components', () => ({
  CodeEditor: ({ value }: { value: string }) => <pre data-testid="code-editor">{value}</pre>,
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}))

vi.mock('@/components/memory/MemoryConfigEditor', () => ({
  MemoryConfigEditor: () => <div data-testid="memory-config-editor">memory-config-editor</div>,
}))

vi.mock('@/components/memory/MemoryDeleteDialog', () => ({
  MemoryDeleteDialog: ({
    open,
    onExecute,
    onRestore,
    preview,
    result,
  }: {
    open: boolean
    preview?: { mode?: string; item_count?: number } | null
    result?: { operation_id?: string } | null
    onExecute?: () => void
    onRestore?: () => void
  }) => (
    open ? (
      <div data-testid="memory-delete-dialog">
        <div>{`preview:${preview?.mode ?? 'none'}:${preview?.item_count ?? 0}`}</div>
        <div>{`result:${result?.operation_id ?? 'none'}`}</div>
        <button type="button" onClick={onExecute}>执行删除</button>
        <button type="button" onClick={onRestore}>执行恢复</button>
      </div>
    ) : null
  ),
}))

vi.mock('@/lib/memory-api', () => ({
  getMemoryConfigSchema: vi.fn(),
  getMemoryConfig: vi.fn(),
  getMemoryConfigRaw: vi.fn(),
  getMemoryRuntimeConfig: vi.fn(),
  getMemoryImportGuide: vi.fn(),
  getMemoryImportSettings: vi.fn(),
  getMemoryImportPathAliases: vi.fn(),
  getMemoryImportTasks: vi.fn(),
  getMemoryImportTask: vi.fn(),
  getMemoryImportTaskChunks: vi.fn(),
  createMemoryUploadImport: vi.fn(),
  createMemoryPasteImport: vi.fn(),
  createMemoryRawScanImport: vi.fn(),
  createMemoryLpmmOpenieImport: vi.fn(),
  createMemoryLpmmConvertImport: vi.fn(),
  createMemoryTemporalBackfillImport: vi.fn(),
  createMemoryMaibotMigrationImport: vi.fn(),
  cancelMemoryImportTask: vi.fn(),
  retryMemoryImportTask: vi.fn(),
  resolveMemoryImportPath: vi.fn(),
  refreshMemoryRuntimeSelfCheck: vi.fn(),
  updateMemoryConfig: vi.fn(),
  updateMemoryConfigRaw: vi.fn(),
  getMemoryTuningProfile: vi.fn(),
  getMemoryTuningTasks: vi.fn(),
  createMemoryTuningTask: vi.fn(),
  applyBestMemoryTuningProfile: vi.fn(),
  getMemorySources: vi.fn(),
  getMemoryDeleteOperations: vi.fn(),
  getMemoryDeleteOperation: vi.fn(),
  getMemoryFeedbackCorrections: vi.fn(),
  getMemoryFeedbackCorrection: vi.fn(),
  previewMemoryDelete: vi.fn(),
  executeMemoryDelete: vi.fn(),
  restoreMemoryDelete: vi.fn(),
  rollbackMemoryFeedbackCorrection: vi.fn(),
}))

function mockImportTask(taskId: string, status: string = 'running'): memoryApi.MemoryImportTaskPayload {
  return {
    task_id: taskId,
    source: 'webui',
    status,
    current_step: status === 'completed' ? 'completed' : 'running',
    total_chunks: 120,
    done_chunks: status === 'completed' ? 120 : 36,
    failed_chunks: status === 'completed' ? 0 : 2,
    cancelled_chunks: 0,
    progress: status === 'completed' ? 100 : 30,
    error: '',
    file_count: 2,
    created_at: 1_710_000_000,
    started_at: 1_710_000_001,
    finished_at: status === 'completed' ? 1_710_000_099 : null,
    updated_at: 1_710_000_100,
    task_kind: 'paste',
    params: {},
    files: [],
  }
}

function mockImportDetail(taskId: string): memoryApi.MemoryImportTaskPayload {
  return {
    ...mockImportTask(taskId),
    files: [
      {
        file_id: 'file-alpha',
        name: 'alpha.txt',
        source_kind: 'paste',
        input_mode: 'text',
        status: 'running',
        current_step: 'running',
        detected_strategy_type: 'auto',
        total_chunks: 80,
        done_chunks: 30,
        failed_chunks: 1,
        cancelled_chunks: 0,
        progress: 37.5,
        error: '',
        created_at: 1_710_000_000,
        updated_at: 1_710_000_100,
      },
      {
        file_id: 'file-beta',
        name: 'beta.txt',
        source_kind: 'paste',
        input_mode: 'text',
        status: 'failed',
        current_step: 'extracting',
        detected_strategy_type: 'auto',
        total_chunks: 40,
        done_chunks: 6,
        failed_chunks: 4,
        cancelled_chunks: 0,
        progress: 25,
        error: 'mock error',
        created_at: 1_710_000_000,
        updated_at: 1_710_000_100,
      },
    ],
  }
}

function mockImportCompletedWithErrorsDetail(taskId: string): memoryApi.MemoryImportTaskPayload {
  return {
    ...mockImportDetail(taskId),
    status: 'completed_with_errors',
    current_step: 'completed_with_errors',
    total_chunks: 12,
    done_chunks: 9,
    failed_chunks: 3,
    cancelled_chunks: 0,
    progress: 75,
    files: [
      {
        file_id: 'file-error',
        name: 'error.txt',
        source_kind: 'paste',
        input_mode: 'text',
        status: 'failed',
        current_step: 'failed',
        detected_strategy_type: 'auto',
        total_chunks: 12,
        done_chunks: 9,
        failed_chunks: 3,
        cancelled_chunks: 0,
        progress: 75,
        error: 'mock error',
        created_at: 1_710_000_000,
        updated_at: 1_710_000_100,
      },
    ],
  }
}

describe('KnowledgeBasePage import workflow', () => {
  beforeEach(() => {
    navigateMock.mockReset()
    toastMock.mockReset()
    vi.mocked(memoryApi.createMemoryUploadImport).mockReset()
    vi.mocked(memoryApi.createMemoryPasteImport).mockReset()
    vi.mocked(memoryApi.createMemoryRawScanImport).mockReset()
    vi.mocked(memoryApi.createMemoryLpmmOpenieImport).mockReset()
    vi.mocked(memoryApi.createMemoryLpmmConvertImport).mockReset()
    vi.mocked(memoryApi.createMemoryTemporalBackfillImport).mockReset()
    vi.mocked(memoryApi.createMemoryMaibotMigrationImport).mockReset()

    vi.mocked(memoryApi.getMemoryConfigSchema).mockResolvedValue({
      success: true,
      path: 'config/a_memorix.toml',
      schema: {
        plugin_id: 'a_memorix',
        plugin_info: {
          name: 'A_Memorix',
          version: '2.0.0',
          description: '长期记忆子系统',
          author: 'A_Dawn',
        },
        _note: 'raw-only 字段仍可通过 TOML 编辑',
        layout: {
          type: 'tabs',
          tabs: [{ id: 'basic', title: '基础', sections: ['plugin'], order: 1 }],
        },
        sections: {
          plugin: {
            name: 'plugin',
            title: '子系统状态',
            collapsed: false,
            order: 1,
            fields: {},
          },
        },
      },
    })
    vi.mocked(memoryApi.getMemoryConfig).mockResolvedValue({
      success: true,
      path: 'config/a_memorix.toml',
      config: { plugin: { enabled: true } },
    })
    vi.mocked(memoryApi.getMemoryConfigRaw).mockResolvedValue({
      success: true,
      path: 'config/a_memorix.toml',
      config: '[plugin]\nenabled = true\n',
    })
    vi.mocked(memoryApi.getMemoryRuntimeConfig).mockResolvedValue({
      success: true,
      config: { plugin: { enabled: true } },
      data_dir: 'data/plugins/a-dawn.a-memorix',
      embedding_dimension: 1024,
      auto_save: true,
      relation_vectors_enabled: false,
      runtime_ready: true,
      embedding_degraded: false,
      embedding_degraded_reason: '',
      embedding_degraded_since: null,
      embedding_last_check: null,
      paragraph_vector_backfill_pending: 2,
      paragraph_vector_backfill_running: 0,
      paragraph_vector_backfill_failed: 1,
      paragraph_vector_backfill_done: 3,
    })

    vi.mocked(memoryApi.getMemoryImportGuide).mockResolvedValue({
      success: true,
      content: '# 导入指南\n导入说明',
    })
    vi.mocked(memoryApi.getMemoryImportSettings).mockResolvedValue({
      success: true,
      settings: {
        max_paste_chars: 200_000,
        max_file_concurrency: 8,
        max_chunk_concurrency: 16,
        default_file_concurrency: 2,
        default_chunk_concurrency: 4,
        poll_interval_ms: 60_000,
        maibot_source_db_default: 'data/maibot.db',
      },
    })
    vi.mocked(memoryApi.getMemoryImportPathAliases).mockResolvedValue({
      success: true,
      path_aliases: {
        lpmm: 'data/lpmm',
        plugin_data: 'data/plugins/a-dawn.a-memorix',
        raw: 'data/raw',
      },
    })
    vi.mocked(memoryApi.getMemoryImportTasks).mockResolvedValue({
      success: true,
      items: [
        mockImportTask('import-run-1', 'running'),
        mockImportTask('import-queued-1', 'queued'),
        mockImportTask('import-done-1', 'completed'),
      ],
    })
    vi.mocked(memoryApi.getMemoryImportTask).mockResolvedValue({
      success: true,
      task: mockImportDetail('import-run-1'),
    })
    vi.mocked(memoryApi.getMemoryImportTaskChunks).mockImplementation(async (_taskId, fileId, offset = 0) => ({
      success: true,
      task_id: 'import-run-1',
      file_id: fileId,
      offset,
      limit: 50,
      total: 120,
      items: [
        {
          chunk_id: `${fileId}-${offset + 0}`,
          index: offset + 0,
          chunk_type: 'text',
          status: 'running',
          step: 'extracting',
          failed_at: '',
          retryable: true,
          error: '',
          progress: 50,
          content_preview: `chunk-preview-${offset + 0}`,
          updated_at: 1_710_000_111,
        },
      ],
    }))

    vi.mocked(memoryApi.createMemoryUploadImport).mockResolvedValue({
      success: true,
      task: mockImportTask('upload-task-1', 'queued'),
    })
    vi.mocked(memoryApi.createMemoryPasteImport).mockResolvedValue({
      success: true,
      task: mockImportTask('paste-task-1', 'queued'),
    })
    vi.mocked(memoryApi.createMemoryRawScanImport).mockResolvedValue({
      success: true,
      task: mockImportTask('raw-task-1', 'queued'),
    })
    vi.mocked(memoryApi.createMemoryLpmmOpenieImport).mockResolvedValue({
      success: true,
      task: mockImportTask('openie-task-1', 'queued'),
    })
    vi.mocked(memoryApi.createMemoryLpmmConvertImport).mockResolvedValue({
      success: true,
      task: mockImportTask('convert-task-1', 'queued'),
    })
    vi.mocked(memoryApi.createMemoryTemporalBackfillImport).mockResolvedValue({
      success: true,
      task: mockImportTask('backfill-task-1', 'queued'),
    })
    vi.mocked(memoryApi.createMemoryMaibotMigrationImport).mockResolvedValue({
      success: true,
      task: mockImportTask('migration-task-1', 'queued'),
    })
    vi.mocked(memoryApi.cancelMemoryImportTask).mockResolvedValue({
      success: true,
      task: mockImportTask('import-run-1', 'cancel_requested'),
    })
    vi.mocked(memoryApi.retryMemoryImportTask).mockResolvedValue({
      success: true,
      task: mockImportTask('retry-task-1', 'queued'),
    })
    vi.mocked(memoryApi.resolveMemoryImportPath).mockResolvedValue({
      success: true,
      alias: 'raw',
      relative_path: 'exports',
      resolved_path: 'D:/Dev/rdev/MaiBot/data/raw/exports',
      exists: true,
      is_file: false,
      is_dir: true,
    })

    vi.mocked(memoryApi.getMemoryTuningProfile).mockResolvedValue({
      success: true,
      profile: { retrieval: { top_k: 10 } },
      toml: '[retrieval]\ntop_k = 10\n',
    })
    vi.mocked(memoryApi.getMemoryTuningTasks).mockResolvedValue({
      success: true,
      items: [{ task_id: 'tune-1', status: 'done' }],
    })
    vi.mocked(memoryApi.createMemoryTuningTask).mockResolvedValue({ success: true } as never)
    vi.mocked(memoryApi.applyBestMemoryTuningProfile).mockResolvedValue({ success: true } as never)

    vi.mocked(memoryApi.getMemorySources).mockResolvedValue({
      success: true,
      items: [{ source: 'demo-1', paragraph_count: 2, relation_count: 1 }],
      count: 1,
    })
    vi.mocked(memoryApi.getMemoryDeleteOperations).mockResolvedValue({
      success: true,
      items: [
        {
          operation_id: 'del-1',
          mode: 'source',
          status: 'executed',
          summary: { counts: { paragraphs: 2, relations: 1, sources: 1 } },
        },
      ],
      count: 1,
    })
    vi.mocked(memoryApi.getMemoryDeleteOperation).mockResolvedValue({
      success: true,
      operation: {
        operation_id: 'del-1',
        mode: 'source',
        status: 'executed',
        selector: { sources: ['demo-1'] },
        summary: { counts: { paragraphs: 2, relations: 1, sources: 1 }, sources: ['demo-1'] },
        items: [],
      },
    })
    vi.mocked(memoryApi.getMemoryFeedbackCorrections).mockResolvedValue({
      success: true,
      items: [
        {
          task_id: 11,
          query_tool_id: 'tool-query-11',
          session_id: 'session-1',
          query_text: '测试用户最喜欢的颜色是什么',
          query_timestamp: 1_710_000_010,
          task_status: 'applied',
          decision: 'correct',
          decision_confidence: 0.97,
          feedback_message_count: 1,
          rollback_status: 'none',
          affected_counts: {
            relations: 1,
            stale_paragraphs: 1,
            episode_sources: 2,
            profile_person_ids: 1,
            correction_paragraphs: 1,
            corrected_relations: 1,
          },
          created_at: 1_710_000_011,
          updated_at: 1_710_000_012,
        },
      ],
      count: 1,
    })
    vi.mocked(memoryApi.getMemoryFeedbackCorrection).mockResolvedValue({
      success: true,
      task: {
        task_id: 11,
        query_tool_id: 'tool-query-11',
        session_id: 'session-1',
        query_text: '测试用户最喜欢的颜色是什么',
        query_timestamp: 1_710_000_010,
        task_status: 'applied',
        decision: 'correct',
        decision_confidence: 0.97,
        feedback_message_count: 1,
        rollback_status: 'none',
        affected_counts: {
          relations: 1,
          stale_paragraphs: 1,
          episode_sources: 2,
          profile_person_ids: 1,
          correction_paragraphs: 1,
          corrected_relations: 1,
        },
        query_snapshot: { query: '测试用户最喜欢的颜色是什么', hits: [{ hash: 'paragraph-1' }] },
        decision_payload: { decision: 'correct', confidence: 0.97 },
        rollback_plan_summary: {
          forgotten_relations: [{ hash: 'rel-old', subject: '测试用户', predicate: '最喜欢的颜色是', object: '蓝色' }],
          corrected_write: {
            paragraph_hashes: ['paragraph-new'],
            corrected_relations: [{ hash: 'rel-new', subject: '测试用户', predicate: '最喜欢的颜色是', object: '绿色' }],
          },
        },
        rollback_result: {},
        action_logs: [
          {
            id: 1,
            task_id: 11,
            query_tool_id: 'tool-query-11',
            action_type: 'forget_relation',
            target_hash: 'rel-old',
            reason: '用户明确纠正为绿色',
            before_payload: { hash: 'rel-old', subject: '测试用户', predicate: '最喜欢的颜色是', object: '蓝色' },
            after_payload: { is_inactive: true },
            created_at: 1_710_000_013,
          },
        ],
        created_at: 1_710_000_011,
        updated_at: 1_710_000_012,
      },
    })
    vi.mocked(memoryApi.previewMemoryDelete).mockResolvedValue({
      success: true,
      mode: 'source',
      selector: { sources: ['demo-1'] },
      counts: { sources: 1, paragraphs: 2, relations: 1 },
      sources: ['demo-1'],
      items: [{ item_type: 'paragraph', item_hash: 'p-1', label: 'demo-1' }],
      item_count: 1,
      dry_run: true,
    } as never)
    vi.mocked(memoryApi.executeMemoryDelete).mockResolvedValue({
      success: true,
      mode: 'source',
      operation_id: 'del-2',
      counts: { sources: 1, paragraphs: 2, relations: 1 },
      sources: ['demo-1'],
      deleted_count: 4,
      deleted_entity_count: 0,
      deleted_relation_count: 1,
      deleted_paragraph_count: 2,
      deleted_source_count: 1,
    } as never)
    vi.mocked(memoryApi.restoreMemoryDelete).mockResolvedValue({ success: true } as never)
    vi.mocked(memoryApi.rollbackMemoryFeedbackCorrection).mockResolvedValue({
      success: true,
      result: { restored_relation_hashes: ['rel-old'] },
      task: {
        task_id: 11,
        query_tool_id: 'tool-query-11',
        session_id: 'session-1',
        query_text: '测试用户最喜欢的颜色是什么',
        query_timestamp: 1_710_000_010,
        task_status: 'applied',
        decision: 'correct',
        decision_confidence: 0.97,
        feedback_message_count: 1,
        rollback_status: 'rolled_back',
        affected_counts: {
          relations: 1,
          stale_paragraphs: 1,
          episode_sources: 2,
          profile_person_ids: 1,
          correction_paragraphs: 1,
          corrected_relations: 1,
        },
        query_snapshot: { query: '测试用户最喜欢的颜色是什么', hits: [{ hash: 'paragraph-1' }] },
        decision_payload: { decision: 'correct', confidence: 0.97 },
        rollback_plan_summary: {},
        rollback_result: { restored_relation_hashes: ['rel-old'] },
        action_logs: [],
        created_at: 1_710_000_011,
        updated_at: 1_710_000_012,
      },
    })
    vi.mocked(memoryApi.refreshMemoryRuntimeSelfCheck).mockResolvedValue({
      success: true,
      report: { ok: true },
    })
    vi.mocked(memoryApi.updateMemoryConfig).mockResolvedValue({ success: true } as never)
    vi.mocked(memoryApi.updateMemoryConfigRaw).mockResolvedValue({ success: true } as never)
  })

  it('loads import settings/guide/tasks on first render', async () => {
    const user = userEvent.setup()
    render(<KnowledgeBasePage />)

    expect(await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: '导入' }))

    expect(await screen.findByRole('button', { name: '创建导入任务' })).toBeInTheDocument()
    expect((await screen.findAllByText('import-run-1')).length).toBeGreaterThan(0)
    expect(memoryApi.getMemoryImportSettings).toHaveBeenCalled()
    expect(memoryApi.getMemoryImportPathAliases).toHaveBeenCalled()
    expect(memoryApi.getMemoryImportTasks).toHaveBeenCalled()
  })

  it('creates import tasks for all 7 modes and calls correct endpoints', async () => {
    const user = userEvent.setup()
    const { container } = render(<KnowledgeBasePage />)

    const openImportTab = async () => {
      await user.click(screen.getByRole('tab', { name: '导入' }))
      await screen.findByRole('button', { name: '创建导入任务' })
    }

    await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })
    await openImportTab()

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    const uploadFiles = [
      new File(['hello'], 'demo.txt', { type: 'text/plain' }),
      new File(['{"name":"mai"}'], 'demo.json', { type: 'application/json' }),
      new File(['a,b\n1,2'], 'demo.csv', { type: 'text/csv' }),
      new File(['# note'], 'demo.md', { type: 'text/markdown' }),
    ]
    await user.upload(fileInput, uploadFiles)
    await user.click(screen.getByRole('button', { name: '创建导入任务' }))
    await waitFor(() => expect(memoryApi.createMemoryUploadImport).toHaveBeenCalledTimes(1))

    await openImportTab()
    await user.click(screen.getByRole('tab', { name: '粘贴导入' }))
    const editableTextarea = Array.from(container.querySelectorAll('textarea')).find((item) => !item.readOnly)
    if (!editableTextarea) {
      throw new Error('missing editable textarea')
    }
    await user.type(editableTextarea, 'paste content')
    await user.click(screen.getByRole('button', { name: '创建导入任务' }))
    await waitFor(() => expect(memoryApi.createMemoryPasteImport).toHaveBeenCalledTimes(1))

    await openImportTab()
    await user.click(screen.getByRole('tab', { name: '本地扫描' }))
    await user.click(screen.getByRole('button', { name: '创建导入任务' }))
    await waitFor(() => expect(memoryApi.createMemoryRawScanImport).toHaveBeenCalledTimes(1))

    await openImportTab()
    await user.click(screen.getByRole('tab', { name: 'LPMM OpenIE' }))
    await user.click(screen.getByRole('button', { name: '创建导入任务' }))
    await waitFor(() => expect(memoryApi.createMemoryLpmmOpenieImport).toHaveBeenCalledTimes(1))

    await openImportTab()
    await user.click(screen.getByRole('tab', { name: 'LPMM 转换' }))
    await user.click(screen.getByRole('button', { name: '创建导入任务' }))
    await waitFor(() => expect(memoryApi.createMemoryLpmmConvertImport).toHaveBeenCalledTimes(1))

    await openImportTab()
    await user.click(screen.getByRole('tab', { name: '时序回填' }))
    await user.click(screen.getByRole('button', { name: '创建导入任务' }))
    await waitFor(() => expect(memoryApi.createMemoryTemporalBackfillImport).toHaveBeenCalledTimes(1))

    await openImportTab()
    await user.click(screen.getByRole('tab', { name: 'MaiBot 迁移' }))
    await user.click(screen.getByRole('button', { name: '创建导入任务' }))
    await waitFor(() => expect(memoryApi.createMemoryMaibotMigrationImport).toHaveBeenCalledTimes(1))

    const [uploadedFiles, uploadPayload] = vi.mocked(memoryApi.createMemoryUploadImport).mock.calls[0]
    expect(uploadedFiles).toHaveLength(4)
    expect(uploadedFiles.map((file) => file.name)).toEqual(['demo.txt', 'demo.json', 'demo.csv', 'demo.md'])
    expect(uploadPayload).toMatchObject({
      input_mode: 'text',
      llm_enabled: true,
      strategy_override: 'auto',
      dedupe_policy: 'content_hash',
    })
  }, 60_000)

  it('formats MaiBot migration datetime-local values and numeric options', async () => {
    const user = userEvent.setup()
    render(<KnowledgeBasePage />)

    await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })
    await user.click(screen.getByRole('tab', { name: '导入' }))
    await screen.findByRole('button', { name: '创建导入任务' })
    await user.click(screen.getByRole('tab', { name: 'MaiBot 迁移' }))

    fireEvent.change(await screen.findByLabelText('源数据库路径'), { target: { value: ' data/old-maibot.db ' } })
    fireEvent.change(screen.getByLabelText('起始时间'), { target: { value: '2024-01-02T03:04' } })
    fireEvent.change(screen.getByLabelText('结束时间'), { target: { value: '2024-01-03T05:06:07' } })
    fireEvent.change(screen.getByLabelText('起始 ID'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('结束 ID'), { target: { value: '20' } })
    await user.click(screen.getByText('高级选项'))
    fireEvent.change(screen.getByLabelText('读取批大小'), { target: { value: '123' } })
    fireEvent.change(screen.getByLabelText('提交窗口行数'), { target: { value: '456' } })
    fireEvent.change(screen.getByLabelText('向量线程数'), { target: { value: '7' } })

    await user.click(screen.getByRole('button', { name: '创建导入任务' }))
    await waitFor(() => expect(memoryApi.createMemoryMaibotMigrationImport).toHaveBeenCalledTimes(1))
    expect(vi.mocked(memoryApi.createMemoryMaibotMigrationImport).mock.calls[0][0]).toMatchObject({
      source_db: 'data/old-maibot.db',
      time_from: '2024-01-02 03:04:00',
      time_to: '2024-01-03 05:06:07',
      start_id: 10,
      end_id: 20,
      read_batch_size: 123,
      commit_window_rows: 456,
      embed_workers: 7,
    })
  }, 20_000)

  it('blocks invalid MaiBot migration input before creating a task', async () => {
    const user = userEvent.setup()
    render(<KnowledgeBasePage />)

    await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })
    await user.click(screen.getByRole('tab', { name: '导入' }))
    await screen.findByRole('button', { name: '创建导入任务' })
    await user.click(screen.getByRole('tab', { name: 'MaiBot 迁移' }))

    const sourceDbInput = await screen.findByLabelText('源数据库路径')
    const createButton = screen.getByRole('button', { name: '创建导入任务' })
    fireEvent.change(sourceDbInput, { target: { value: '   ' } })
    await user.click(createButton)
    await waitFor(() =>
      expect(toastMock).toHaveBeenLastCalledWith(expect.objectContaining({ description: '请填写源数据库路径' })),
    )
    expect(memoryApi.createMemoryMaibotMigrationImport).not.toHaveBeenCalled()

    fireEvent.change(sourceDbInput, { target: { value: 'data/old-maibot.db' } })
    fireEvent.change(screen.getByLabelText('起始时间'), { target: { value: '2024-01-03T00:00' } })
    fireEvent.change(screen.getByLabelText('结束时间'), { target: { value: '2024-01-02T00:00' } })
    await user.click(createButton)
    await waitFor(() =>
      expect(toastMock).toHaveBeenLastCalledWith(expect.objectContaining({ description: '起始时间不能晚于结束时间' })),
    )
    expect(memoryApi.createMemoryMaibotMigrationImport).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('起始时间'), { target: { value: '2024-01-02T00:00' } })
    fireEvent.change(screen.getByLabelText('结束时间'), { target: { value: '2024-01-03T00:00' } })
    fireEvent.change(screen.getByLabelText('起始 ID'), { target: { value: '20' } })
    fireEvent.change(screen.getByLabelText('结束 ID'), { target: { value: '10' } })
    await user.click(createButton)
    await waitFor(() =>
      expect(toastMock).toHaveBeenLastCalledWith(expect.objectContaining({ description: '起始 ID 不能大于结束 ID' })),
    )
    expect(memoryApi.createMemoryMaibotMigrationImport).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('起始 ID'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('结束 ID'), { target: { value: '20' } })
    await user.click(screen.getByText('高级选项'))
    fireEvent.change(screen.getByLabelText('读取批大小'), { target: { value: '0' } })
    await user.click(createButton)
    await waitFor(() =>
      expect(toastMock).toHaveBeenLastCalledWith(expect.objectContaining({ description: '读取批大小 必须填写正整数' })),
    )
    expect(memoryApi.createMemoryMaibotMigrationImport).not.toHaveBeenCalled()
  }, 20_000)

  it('loads task detail and supports chunk pagination', async () => {
    const user = userEvent.setup()
    render(<KnowledgeBasePage />)

    await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })
    await user.click(screen.getByRole('tab', { name: '导入' }))

    expect(await screen.findByText('alpha.txt')).toBeInTheDocument()
    expect(await screen.findByText('chunk-preview-0')).toBeInTheDocument()

    const betaButton = screen.getByText('beta.txt').closest('button')
    if (!betaButton) {
      throw new Error('missing file beta button')
    }
    await user.click(betaButton)
    await waitFor(() =>
      expect(memoryApi.getMemoryImportTaskChunks).toHaveBeenCalledWith('import-run-1', 'file-beta', 0, 50),
    )

    await user.click(screen.getByRole('button', { name: '下一页分块' }))
    await waitFor(() =>
      expect(memoryApi.getMemoryImportTaskChunks).toHaveBeenCalledWith('import-run-1', 'file-beta', 50, 50),
    )
  }, 20_000)

  it('shows import failures separately from successful chunks', async () => {
    vi.mocked(memoryApi.getMemoryImportTask).mockResolvedValue({
      success: true,
      task: mockImportCompletedWithErrorsDetail('import-run-1'),
    })
    const user = userEvent.setup()
    render(<KnowledgeBasePage />)

    await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })
    await user.click(screen.getByRole('tab', { name: '导入' }))

    expect((await screen.findAllByText('完成（有错误）')).length).toBeGreaterThan(0)
    expect(await screen.findByText('成功 9 / 12 分块 · 失败 3')).toBeInTheDocument()
  }, 20_000)

  it('supports cancel and retry actions for selected task', async () => {
    const user = userEvent.setup()
    render(<KnowledgeBasePage />)

    await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })
    await user.click(screen.getByRole('tab', { name: '导入' }))
    await screen.findByText('任务详情')

    await user.click(screen.getByRole('button', { name: '取消选中导入任务' }))
    await waitFor(() => expect(memoryApi.cancelMemoryImportTask).toHaveBeenCalledWith('import-run-1'))

    await user.click(screen.getByRole('button', { name: '重试选中导入任务' }))
    await waitFor(() => expect(memoryApi.retryMemoryImportTask).toHaveBeenCalled())
    const [taskId, retryPayload] = vi.mocked(memoryApi.retryMemoryImportTask).mock.calls[0]
    expect(taskId).toBe('import-run-1')
    expect(retryPayload).toMatchObject({
      overrides: {
        llm_enabled: true,
        strategy_override: 'auto',
      },
    })
  }, 20_000)

  it('auto polling updates queue and keeps page stable when refresh fails once', async () => {
    vi.mocked(memoryApi.getMemoryImportSettings).mockResolvedValue({
      success: true,
      settings: {
        max_paste_chars: 200_000,
        max_file_concurrency: 8,
        max_chunk_concurrency: 16,
        default_file_concurrency: 2,
        default_chunk_concurrency: 4,
        poll_interval_ms: 200,
        maibot_source_db_default: 'data/maibot.db',
      },
    })
    const user = userEvent.setup()
    render(<KnowledgeBasePage />)

    await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })
    await user.click(screen.getByRole('tab', { name: '导入' }))
    await screen.findByText('导入队列')

    const initialCalls = vi.mocked(memoryApi.getMemoryImportTasks).mock.calls.length
    vi.mocked(memoryApi.getMemoryImportTasks).mockRejectedValueOnce(new Error('poll failure'))
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 350))
    })

    expect(screen.getByText('长期记忆控制台')).toBeInTheDocument()
    expect(vi.mocked(memoryApi.getMemoryImportTasks).mock.calls.length).toBeGreaterThan(initialCalls)
  }, 20_000)

  it('creates tuning task and applies best profile (tuning module)', async () => {
    const user = userEvent.setup()
    render(<KnowledgeBasePage />)

    await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })
    await user.click(screen.getByRole('tab', { name: '调优' }))
    await screen.findByText('调优任务')

    await user.click(screen.getByRole('button', { name: '创建调优任务' }))
    await waitFor(() =>
      expect(memoryApi.createMemoryTuningTask).toHaveBeenCalledWith({
        objective: 'precision_priority',
        intensity: 'standard',
        sample_size: 24,
        top_k_eval: 20,
      }),
    )

    await user.click(screen.getByRole('button', { name: '应用最佳' }))
    await waitFor(() => expect(memoryApi.applyBestMemoryTuningProfile).toHaveBeenCalledWith('tune-1'))
  }, 20_000)

  it('previews executes and restores source delete (delete module)', async () => {
    const user = userEvent.setup()
    render(<KnowledgeBasePage />)

    await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })
    await user.click(screen.getByRole('tab', { name: '删除' }))
    await screen.findByText('来源批量删除')

    const sourceCellCandidates = await screen.findAllByText('demo-1')
    const sourceRow = sourceCellCandidates
      .map((item) => item.closest('tr'))
      .find((row): row is HTMLTableRowElement => Boolean(row && within(row).queryByRole('checkbox')))
    if (!sourceRow) {
      throw new Error('missing source row')
    }
    await user.click(within(sourceRow).getByRole('checkbox'))

    await user.click(screen.getByRole('button', { name: '预览删除' }))
    await waitFor(() =>
      expect(memoryApi.previewMemoryDelete).toHaveBeenCalledWith({
        mode: 'source',
        selector: { sources: ['demo-1'] },
        reason: 'knowledge_base_source_delete',
        requested_by: 'knowledge_base',
      }),
    )

    const dialog = await screen.findByTestId('memory-delete-dialog')
    expect(dialog).toHaveTextContent('preview:source:1')

    await user.click(screen.getByRole('button', { name: '执行删除' }))
    await waitFor(() =>
      expect(memoryApi.executeMemoryDelete).toHaveBeenCalledWith({
        mode: 'source',
        selector: { sources: ['demo-1'] },
        reason: 'knowledge_base_source_delete',
        requested_by: 'knowledge_base',
      }),
    )

    await user.click(screen.getByRole('button', { name: '执行恢复' }))
    await waitFor(() =>
      expect(memoryApi.restoreMemoryDelete).toHaveBeenCalledWith({
        operation_id: 'del-2',
        requested_by: 'knowledge_base',
      }),
    )
  }, 20_000)

  it('shows feedback correction history and supports rollback', async () => {
    const user = userEvent.setup()
    render(<KnowledgeBasePage />)

    await screen.findByText('长期记忆控制台', undefined, { timeout: 10_000 })
    await user.click(screen.getByRole('tab', { name: '纠错历史' }))
    await screen.findByText('反馈纠错历史')
    await screen.findByText('测试用户最喜欢的颜色是什么')
    await waitFor(() => expect(memoryApi.getMemoryFeedbackCorrection).toHaveBeenCalledWith(11))

    await user.click(screen.getByRole('button', { name: '回退本次纠错' }))
    const rollbackReason = await screen.findByLabelText('回退原因')
    await user.type(rollbackReason, '人工确认回退')
    await user.click(screen.getByRole('button', { name: '确认回退' }))

    await waitFor(() =>
      expect(memoryApi.rollbackMemoryFeedbackCorrection).toHaveBeenCalledWith(11, {
        requested_by: 'knowledge_base',
        reason: '人工确认回退',
      }),
    )
  }, 20_000)
})
