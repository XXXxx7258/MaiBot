import { useEffect, useState } from 'react'
import { Download, Star, ThumbsDown, ThumbsUp } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/hooks/use-toast'
import {
  dislikePlugin,
  getPluginStats,
  getPluginUserState,
  likePlugin,
  ratePlugin,
  type PluginStatsData,
  type VoteStatsResponse,
} from '@/lib/plugin-stats'

interface PluginStatsProps {
  pluginId: string
  compact?: boolean
}

export function PluginStats({ pluginId, compact = false }: PluginStatsProps) {
  const [stats, setStats] = useState<PluginStatsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [userRating, setUserRating] = useState(0)
  const [userComment, setUserComment] = useState('')
  const [liked, setLiked] = useState(false)
  const [disliked, setDisliked] = useState(false)
  const [actionLoading, setActionLoading] = useState<'like' | 'dislike' | 'rating' | null>(null)
  const [isRatingDialogOpen, setIsRatingDialogOpen] = useState(false)
  const { toast } = useToast()

  const loadStats = async () => {
    setLoading(true)
    const [statsData, userState] = await Promise.all([
      getPluginStats(pluginId),
      getPluginUserState(pluginId),
    ])

    if (statsData) {
      setStats(statsData)
    }
    if (userState) {
      setLiked(userState.liked)
      setDisliked(userState.disliked)
      setUserRating(userState.rating)
      setUserComment(userState.comment)
    }
    setLoading(false)
  }

  useEffect(() => {
    void loadStats()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pluginId])

  const updateVoteStats = (result: VoteStatsResponse) => {
    setLiked(result.liked === true)
    setDisliked(result.disliked === true)
    setStats((currentStats) => currentStats
      ? {
        ...currentStats,
        likes: Number(result.likes ?? currentStats.likes),
        dislikes: Number(result.dislikes ?? currentStats.dislikes),
      }
      : currentStats)
  }

  const handleLike = async () => {
    setActionLoading('like')
    const result = await likePlugin(pluginId)
    setActionLoading(null)

    if (result.success) {
      updateVoteStats(result)
      toast({
        title: result.liked ? '已点赞' : '已取消点赞',
        description: result.liked ? '感谢你的支持' : '已更新你的反馈状态',
      })
      return
    }

    toast({
      title: '点赞失败',
      description: result.error || '未知错误',
      variant: 'destructive',
    })
  }

  const handleDislike = async () => {
    setActionLoading('dislike')
    const result = await dislikePlugin(pluginId)
    setActionLoading(null)

    if (result.success) {
      updateVoteStats(result)
      toast({
        title: result.disliked ? '已点踩' : '已取消点踩',
        description: '已更新你的反馈状态',
      })
      return
    }

    toast({
      title: '操作失败',
      description: result.error || '未知错误',
      variant: 'destructive',
    })
  }

  const handleSubmitRating = async () => {
    if (userRating === 0) {
      toast({
        title: '请选择评分',
        description: '至少选择 1 颗星',
        variant: 'destructive',
      })
      return
    }

    setActionLoading('rating')
    const result = await ratePlugin(pluginId, userRating, userComment || undefined)
    setActionLoading(null)

    if (result.success) {
      setUserRating(Number(result.user_rating ?? userRating))
      setStats((currentStats) => currentStats
        ? {
          ...currentStats,
          rating: Number(result.rating ?? currentStats.rating),
          rating_count: Number(result.rating_count ?? currentStats.rating_count),
        }
        : currentStats)
      setIsRatingDialogOpen(false)
      toast({ title: '评分已更新', description: '你的当前评分已覆盖保存' })
      return
    }

    toast({
      title: '评分失败',
      description: result.error || '未知错误',
      variant: 'destructive',
    })
  }

  if (loading) {
    return (
      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        <div className="flex items-center gap-1">
          <Download className="h-4 w-4" />
          <span>-</span>
        </div>
        <div className="flex items-center gap-1">
          <Star className="h-4 w-4" />
          <span>-</span>
        </div>
      </div>
    )
  }

  if (!stats) {
    return null
  }

  if (compact) {
    return (
      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        <div className="flex items-center gap-1" title={`下载量: ${stats.downloads.toLocaleString()}`}>
          <Download className="h-4 w-4" />
          <span>{stats.downloads.toLocaleString()}</span>
        </div>
        <div className="flex items-center gap-1" title={`评分: ${stats.rating.toFixed(1)} (${stats.rating_count} 条评价)`}>
          <Star className="h-4 w-4 fill-yellow-400 text-yellow-400" />
          <span>{stats.rating.toFixed(1)}</span>
        </div>
        <div className="flex items-center gap-1" title={`点赞数: ${stats.likes}`}>
          <ThumbsUp className="h-4 w-4" />
          <span>{stats.likes}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="flex flex-col items-center rounded-lg border bg-card p-3">
          <Download className="mb-1 h-5 w-5 text-muted-foreground" />
          <span className="text-2xl font-bold">{stats.downloads.toLocaleString()}</span>
          <span className="text-xs text-muted-foreground">下载量</span>
        </div>

        <div className="flex flex-col items-center rounded-lg border bg-card p-3">
          <Star className="mb-1 h-5 w-5 fill-yellow-400 text-yellow-400" />
          <span className="text-2xl font-bold">{stats.rating.toFixed(1)}</span>
          <span className="text-xs text-muted-foreground">{stats.rating_count} 条评价</span>
        </div>

        <div className="flex flex-col items-center rounded-lg border bg-card p-3">
          <ThumbsUp className="mb-1 h-5 w-5 text-green-500" />
          <span className="text-2xl font-bold">{stats.likes}</span>
          <span className="text-xs text-muted-foreground">点赞</span>
        </div>

        <div className="flex flex-col items-center rounded-lg border bg-card p-3">
          <ThumbsDown className="mb-1 h-5 w-5 text-red-500" />
          <span className="text-2xl font-bold">{stats.dislikes}</span>
          <span className="text-xs text-muted-foreground">点踩</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant={liked ? 'default' : 'outline'}
          size="sm"
          onClick={handleLike}
          disabled={actionLoading !== null}
        >
          <ThumbsUp className="mr-1 h-4 w-4" />
          {liked ? '已点赞' : '点赞'}
        </Button>

        <Button
          variant={disliked ? 'destructive' : 'outline'}
          size="sm"
          onClick={handleDislike}
          disabled={actionLoading !== null}
        >
          <ThumbsDown className="mr-1 h-4 w-4" />
          {disliked ? '已点踩' : '点踩'}
        </Button>

        <Dialog open={isRatingDialogOpen} onOpenChange={setIsRatingDialogOpen}>
          <DialogTrigger asChild>
            <Button variant="default" size="sm" disabled={actionLoading !== null}>
              <Star className="mr-1 h-4 w-4" />
              {userRating > 0 ? '修改评分' : '评分'}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>为插件评分</DialogTitle>
              <DialogDescription>再次提交会覆盖你之前的评分。</DialogDescription>
            </DialogHeader>

            <div className="space-y-4 py-4">
              <div className="flex flex-col items-center gap-2">
                <div className="flex gap-2">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <button
                      key={star}
                      type="button"
                      onClick={() => setUserRating(star)}
                      className="focus:outline-none"
                    >
                      <Star
                        className={`h-8 w-8 transition-colors ${
                          star <= userRating
                            ? 'fill-yellow-400 text-yellow-400'
                            : 'text-muted-foreground hover:text-yellow-300'
                        }`}
                      />
                    </button>
                  ))}
                </div>
                <span className="text-sm text-muted-foreground">
                  {userRating === 0 && '点击星星进行评分'}
                  {userRating === 1 && '很差'}
                  {userRating === 2 && '一般'}
                  {userRating === 3 && '还行'}
                  {userRating === 4 && '不错'}
                  {userRating === 5 && '非常好'}
                </span>
              </div>

              <div>
                <label htmlFor="plugin-rating-comment" className="mb-2 block text-sm font-medium">
                  评论（可选）
                </label>
                <Textarea
                  value={userComment}
                  id="plugin-rating-comment"
                  onChange={(event) => setUserComment(event.target.value)}
                  placeholder="分享你的使用体验..."
                  rows={4}
                  maxLength={500}
                />
                <div className="mt-1 text-right text-xs text-muted-foreground">
                  {userComment.length} / 500
                </div>
              </div>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => setIsRatingDialogOpen(false)}>
                取消
              </Button>
              <Button onClick={handleSubmitRating} disabled={userRating === 0 || actionLoading !== null}>
                {actionLoading === 'rating' ? '提交中...' : '提交评分'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {stats.recent_ratings && stats.recent_ratings.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold">最近评价</h4>
          <div className="space-y-3">
            {stats.recent_ratings.map((rating, index) => (
              <div key={`${rating.user_id}-${rating.created_at}-${index}`} className="rounded-lg border bg-muted/50 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <div className="flex gap-1">
                    {[1, 2, 3, 4, 5].map((star) => (
                      <Star
                        key={star}
                        className={`h-3 w-3 ${
                          star <= rating.rating
                            ? 'fill-yellow-400 text-yellow-400'
                            : 'text-muted-foreground'
                        }`}
                      />
                    ))}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {new Date(rating.created_at).toLocaleDateString()}
                  </span>
                </div>
                {rating.comment && (
                  <p className="text-sm text-muted-foreground">{rating.comment}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
