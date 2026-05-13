import { fetchWithAuth, getAuthHeaders } from './fetch-with-auth'

/**
 * 系统控制 API
 */

/**
 * 重启麦麦主程序
 */
export async function restartMaiBot(): Promise<{ success: boolean; message: string }> {
  const response = await fetchWithAuth('/api/webui/system/restart', {
    method: 'POST',
    headers: getAuthHeaders(),
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '重启失败')
  }
  
  return await response.json()
}

/**
 * 检查麦麦运行状态
 */
export async function getMaiBotStatus(): Promise<{
  running: boolean
  uptime: number
  version: string
  start_time: string
}> {
  const response = await fetchWithAuth('/api/webui/system/status', {
    method: 'GET',
    headers: getAuthHeaders(),
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '获取状态失败')
  }
  
  return await response.json()
}

export interface CacheDirectoryStats {
  key: string
  label: string
  path: string
  exists: boolean
  file_count: number
  total_size: number
  db_records: number
}

export interface DatabaseFileStats {
  path: string
  exists: boolean
  size: number
}

export interface DatabaseTableStats {
  name: string
  rows: number
}

export interface DatabaseStorageStats {
  files: DatabaseFileStats[]
  tables: DatabaseTableStats[]
  total_size: number
}

export interface LocalCacheStats {
  directories: CacheDirectoryStats[]
  database: DatabaseStorageStats
}

export interface LocalCacheCleanupResult {
  success: boolean
  message: string
  target: 'images' | 'emoji' | 'log_files' | 'database_logs'
  removed_files: number
  removed_bytes: number
  removed_records: number
}

export type LocalCacheCleanupTarget = LocalCacheCleanupResult['target']
export type LogCleanupTable = 'llm_usage' | 'tool_records' | 'mai_messages'

export async function getLocalCacheStats(): Promise<LocalCacheStats> {
  const response = await fetchWithAuth('/api/webui/system/local-cache', {
    method: 'GET',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '获取本地缓存统计失败')
  }

  return await response.json()
}

export async function cleanupLocalCache(
  target: LocalCacheCleanupTarget,
  tables: LogCleanupTable[] = []
): Promise<LocalCacheCleanupResult> {
  const response = await fetchWithAuth('/api/webui/system/local-cache/cleanup', {
    method: 'POST',
    headers: {
      ...getAuthHeaders(),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ target, tables }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '清理本地缓存失败')
  }

  return await response.json()
}
