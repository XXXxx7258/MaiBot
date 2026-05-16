import type { GitStatus, MaimaiVersion, MarketplaceSortKey, PluginInfo, PluginLoadProgress, PluginStatsData } from './types'
import { PluginCard } from './PluginCard'

interface MarketplaceTabProps {
  plugins: PluginInfo[]
  searchQuery: string
  categoryFilter: string
  showCompatibleOnly: boolean
  sortBy: MarketplaceSortKey
  gitStatus: GitStatus | null
  maimaiVersion: MaimaiVersion | null
  pluginStats: Record<string, PluginStatsData>
  loadProgress: PluginLoadProgress | null
  onInstall: (plugin: PluginInfo) => void
  onUpdate: (plugin: PluginInfo) => void
  onUninstall: (plugin: PluginInfo) => void
  checkPluginCompatibility: (plugin: PluginInfo) => boolean
  needsUpdate: (plugin: PluginInfo) => boolean
  getStatusBadge: (plugin: PluginInfo) => React.JSX.Element | null
  getIncompatibleReason: (plugin: PluginInfo) => string | null
}

export function MarketplaceTab({
  plugins,
  searchQuery,
  categoryFilter,
  showCompatibleOnly,
  sortBy,
  gitStatus,
  maimaiVersion,
  pluginStats,
  loadProgress,
  onInstall,
  onUpdate,
  onUninstall,
  checkPluginCompatibility,
  needsUpdate,
  getStatusBadge,
  getIncompatibleReason,
}: MarketplaceTabProps) {
  // 过滤插件
  const getPluginStats = (plugin: PluginInfo): PluginStatsData | undefined => {
    const statsIds = [
      plugin.manifest?.id,
      plugin.id,
    ].filter((id): id is string => Boolean(id))

    return statsIds.map((id) => pluginStats[id]).find(Boolean)
  }

  const getSortValue = (plugin: PluginInfo): number => {
    const stats = getPluginStats(plugin)

    if (sortBy === 'default') {
      const downloads = stats?.downloads ?? plugin.downloads ?? 0
      const likes = stats?.likes ?? 0
      const rating = stats?.rating ?? plugin.rating ?? 0
      const ratingCount = stats?.rating_count ?? 0

      return Math.log10(downloads + 1) * 4
        + Math.log10(likes + 1) * 3
        + rating * Math.log10(ratingCount + 2) * 2
    }
    if (sortBy === 'downloads') {
      return stats?.downloads ?? plugin.downloads ?? 0
    }
    if (sortBy === 'likes') {
      return stats?.likes ?? 0
    }
    if (sortBy === 'rating') {
      return stats?.rating ?? plugin.rating ?? 0
    }

    return 0
  }

  const filteredPlugins = plugins.filter(plugin => {
    // 跳过没有 manifest 的插件
    if (!plugin.manifest) {
      console.warn('[过滤] 跳过无 manifest 的插件:', plugin.id)
      return false
    }

    // 全部插件只展示 plugin-repo 中存在的市场插件，本地独有插件只在“已安装”显示。
    if (plugin.source === 'local') {
      return false
    }
    
    // 搜索过滤
    const matchesSearch = searchQuery === '' ||
      plugin.manifest.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      plugin.manifest.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (plugin.manifest.keywords && plugin.manifest.keywords.some(k => k.toLowerCase().includes(searchQuery.toLowerCase())))
    
    // 分类过滤
    const matchesCategory = categoryFilter === 'all' ||
      (plugin.manifest.categories && plugin.manifest.categories.includes(categoryFilter))
    
    // 兼容性过滤
    const matchesCompatibility = !showCompatibleOnly || 
      !maimaiVersion || 
      checkPluginCompatibility(plugin)
    
    return matchesSearch && matchesCategory && matchesCompatibility
  }).sort((left, right) => {
    const valueDiff = getSortValue(right) - getSortValue(left)
    if (valueDiff !== 0) {
      return valueDiff
    }

    return (left.manifest?.name || left.id).localeCompare(right.manifest?.name || right.id)
  })

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-5">
      {filteredPlugins.map((plugin) => (
        <PluginCard
          key={plugin.id}
          plugin={plugin}
          gitStatus={gitStatus}
          maimaiVersion={maimaiVersion}
          pluginStats={pluginStats}
          loadProgress={loadProgress}
          onInstall={onInstall}
          onUpdate={onUpdate}
          onUninstall={onUninstall}
          checkPluginCompatibility={checkPluginCompatibility}
          needsUpdate={needsUpdate}
          getStatusBadge={getStatusBadge}
          getIncompatibleReason={getIncompatibleReason}
        />
      ))}
    </div>
  )
}
