/**
 * 閹绘帊娆㈢紒鐔活吀 API 鐎广垺鍩涚粩?
 * 閻劋绨稉?Cloudflare Workers 缂佺喕顓搁張宥呭娴溿倓绨?
 */

// 闁板秶鐤嗙紒鐔活吀閺堝秴濮?API 閸︽澘娼冮敍鍫熷閺堝鏁ら幋宄板彙娴滎偆娈戞禍鎴狀伂缂佺喕顓搁張宥呭閿?
import { fetchWithAuth } from '@/lib/fetch-with-auth'

const STATS_API_BASE_URL = '/api/webui/plugins/stats-proxy'

export interface PluginStatsData {
  plugin_id: string
  likes: number
  dislikes: number
  downloads: number
  rating: number
  rating_count: number
  recent_ratings?: Array<{
    user_id: string
    rating: number
    comment?: string
    created_at: string
  }>
}

export interface StatsResponse {
  success: boolean
  error?: string
  remaining?: number
  [key: string]: unknown
}

interface PluginStatsSummaryResponse {
  success?: boolean
  stats?: Record<string, Partial<PluginStatsData>>
  error?: string
}

function createEmptyStats(pluginId: string): PluginStatsData {
  return {
    plugin_id: pluginId,
    likes: 0,
    dislikes: 0,
    downloads: 0,
    rating: 0,
    rating_count: 0,
  }
}

function normalizePluginStatsResponse(data: unknown, pluginId: string): PluginStatsData | null {
  if (!data || typeof data !== 'object') {
    return null
  }

  const response = data as Partial<PluginStatsData> & {
    stats?: Partial<PluginStatsData>
  }
  const stats = response.stats ?? response

  return {
    ...createEmptyStats(pluginId),
    ...stats,
    plugin_id: String(stats.plugin_id ?? pluginId),
    likes: Number(stats.likes ?? 0),
    dislikes: Number(stats.dislikes ?? 0),
    downloads: Number(stats.downloads ?? 0),
    rating: Number(stats.rating ?? 0),
    rating_count: Number(stats.rating_count ?? 0),
    recent_ratings: Array.isArray(stats.recent_ratings) ? stats.recent_ratings : undefined,
  }
}

/**
 * 閼惧嘲褰囬幓鎺嶆缂佺喕顓搁弫鐗堝祦
 */
export async function getPluginStats(pluginId: string): Promise<PluginStatsData | null> {
  try {
    const response = await fetchWithAuth(`${STATS_API_BASE_URL}/stats/${encodeURIComponent(pluginId)}`)
    
    if (!response.ok) {
      console.error('Failed to fetch plugin stats:', response.statusText)
      return null
    }
    
    return normalizePluginStatsResponse(await response.json(), pluginId)
  } catch (error) {
    console.error('Error fetching plugin stats:', error)
    return null
  }
}

/**
 * 閼惧嘲褰囬幓鎺嶆鐢倸婧€閻ㄥ嫯浜ら柌蹇曠埠鐠佲剝鎲崇憰渚婄礄娑撳秴瀵橀崥顐ョ槑鐠佺尨绱氶妴? */
export async function getPluginStatsSummary(): Promise<Record<string, PluginStatsData>> {
  try {
    const response = await fetchWithAuth(`${STATS_API_BASE_URL}/stats/summary`)

    if (!response.ok) {
      console.error('Failed to fetch plugin stats summary:', response.statusText)
      return {}
    }

    const data = await response.json() as PluginStatsSummaryResponse
    if (!data.success || !data.stats || typeof data.stats !== 'object') {
      return {}
    }

    return Object.fromEntries(
      Object.entries(data.stats).map(([pluginId, stats]) => [
        pluginId,
        normalizePluginStatsResponse({ stats }, pluginId) ?? createEmptyStats(pluginId),
      ])
    )
  } catch (error) {
    console.error('Error fetching plugin stats summary:', error)
    return {}
  }
}


/**
 * 閻愮绂愰幓鎺嶆
 */
export async function likePlugin(pluginId: string, userId?: string): Promise<StatsResponse> {
  try {
    const finalUserId = userId || getUserId()
    
    const response = await fetchWithAuth(`${STATS_API_BASE_URL}/stats/like`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ plugin_id: pluginId, user_id: finalUserId }),
    })
    
    const data = await response.json()
    
    if (response.status === 429) {
      return { success: false, error: '閹垮秳缍旀潻鍥︾艾妫版垹绠掗敍宀冾嚞缁嬪秴鎮楅崘宥堢槸' }
    }
    
    if (!response.ok) {
      return { success: false, error: data.error || '閻愮绂愭径杈Е' }
    }
    
    return { success: true, ...data }
  } catch (error) {
    console.error('Error liking plugin:', error)
    return { success: false, error: '缂冩垹绮堕柨娆掝嚖' }
  }
}

/**
 * 閻愮淇幓鎺嶆
 */
export async function dislikePlugin(pluginId: string, userId?: string): Promise<StatsResponse> {
  try {
    const finalUserId = userId || getUserId()
    
    const response = await fetchWithAuth(`${STATS_API_BASE_URL}/stats/dislike`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ plugin_id: pluginId, user_id: finalUserId }),
    })
    
    const data = await response.json()
    
    if (response.status === 429) {
      return { success: false, error: '閹垮秳缍旀潻鍥︾艾妫版垹绠掗敍宀冾嚞缁嬪秴鎮楅崘宥堢槸' }
    }
    
    if (!response.ok) {
      return { success: false, error: data.error || '閻愮淇径杈Е' }
    }
    
    return { success: true, ...data }
  } catch (error) {
    console.error('Error disliking plugin:', error)
    return { success: false, error: '缂冩垹绮堕柨娆掝嚖' }
  }
}

/**
 * 鐠囧嫬鍨庨幓鎺嶆
 */
export async function ratePlugin(
  pluginId: string,
  rating: number,
  comment?: string,
  userId?: string
): Promise<StatsResponse> {
  if (rating < 1 || rating > 5) {
    return { success: false, error: '评分必须在 1-5 之间' }
  }
  
  try {
    const finalUserId = userId || getUserId()
    
    const response = await fetchWithAuth(`${STATS_API_BASE_URL}/stats/rate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ plugin_id: pluginId, rating, comment, user_id: finalUserId }),
    })
    
    const data = await response.json()
    
    if (response.status === 429) {
      return { success: false, error: '每天最多评分 3 次' }
    }
    
    if (!response.ok) {
      return { success: false, error: data.error || '鐠囧嫬鍨庢径杈Е' }
    }
    
    return { success: true, ...data }
  } catch (error) {
    console.error('Error rating plugin:', error)
    return { success: false, error: '缂冩垹绮堕柨娆掝嚖' }
  }
}

/**
 * 鐠佹澘缍嶉幓鎺嶆娑撳娴?
 */
export async function recordPluginDownload(pluginId: string): Promise<StatsResponse> {
  try {
    const response = await fetchWithAuth(`${STATS_API_BASE_URL}/stats/download`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ plugin_id: pluginId }),
    })
    
    const data = await response.json()
    
    if (response.status === 429) {
      // 娑撳娴囩紒鐔活吀鐞氼偊妾哄ù浣规闂堟瑩绮径杈Е閿涘奔绗夎ぐ鍗炴惙閻劍鍩涙担鎾荤崣
      console.warn('Download recording rate limited')
      return { success: true }
    }
    
    if (!response.ok) {
      console.error('Failed to record download:', data.error)
      return { success: false, error: data.error }
    }
    
    return { success: true, ...data }
  } catch (error) {
    console.error('Error recording download:', error)
    return { success: false, error: '缂冩垹绮堕柨娆掝嚖' }
  }
}

/**
 * 閻㈢喐鍨氶悽銊﹀煕閹稿洨姹楅敍鍫濈唨娴滃孩绁荤憴鍫濇珤閻楃懓绶涢敍?
 * 閻劋绨崷銊︽弓閻ц缍嶉弮鎯扮槕閸掝偆鏁ら幋鍑ょ礉闂冨弶顒涢柌宥咁槻閹舵洜銈?
 */
export function generateUserFingerprint(): string {
  const nav = navigator as Navigator & { deviceMemory?: number }
  const features = [
    navigator.userAgent,
    navigator.language,
    navigator.languages?.join(',') || '',
    navigator.platform,
    navigator.hardwareConcurrency || 0,
    screen.width,
    screen.height,
    screen.colorDepth,
    screen.pixelDepth,
    new Date().getTimezoneOffset(),
    Intl.DateTimeFormat().resolvedOptions().timeZone,
    navigator.maxTouchPoints || 0,
    nav.deviceMemory || 0,
  ].join('|')
  
  // 缁犫偓閸楁洖鎼辩敮灞藉毐閺?
  let hash = 0
  for (let i = 0; i < features.length; i++) {
    const char = features.charCodeAt(i)
    hash = ((hash << 5) - hash) + char
    hash = hash & hash // Convert to 32bit integer
  }
  
  return `fp_${Math.abs(hash).toString(36)}`
}

/**
 * 閻㈢喐鍨氶幋鏍箯閸欐牜鏁ら幋?UUID
 * 鐎涙ê鍋嶉崷?localStorage 娑擃厽瀵旀稊鍛
 */
export function getUserId(): string {
  const STORAGE_KEY = 'maibot_user_id'
  
  // 鐏忔繆鐦禒?localStorage 閼惧嘲褰?
  let userId = localStorage.getItem(STORAGE_KEY)
  
  if (!userId) {
    // 閻㈢喐鍨氶弬鎵畱 UUID
    const fingerprint = generateUserFingerprint()
    const timestamp = Date.now().toString(36)
    const random = Math.random().toString(36).substring(2, 15)
    
    userId = `${fingerprint}_${timestamp}_${random}`
    
    // 鐎涙ê鍋嶉崚?localStorage
    localStorage.setItem(STORAGE_KEY, userId)
  }
  
  return userId
}
