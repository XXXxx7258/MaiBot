import { useState, useEffect, useCallback } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ListFieldEditor } from '@/components/ListFieldEditor'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { CodeEditor } from '@/components/CodeEditor'
import { parse as parseToml } from 'smol-toml'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Settings,
  Package,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  ChevronRight,
  ChevronDown,
  Save,
  RotateCcw,
  Power,
  Loader2,
  Search,
  ArrowLeft,
  Info,
  Eye,
  EyeOff,
  RotateCw,
  Code2,
  Layout,
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { RestartProvider, useRestart } from '@/lib/restart-context'
import { RestartOverlay } from '@/components/restart-overlay'
import {
  getInstalledPlugins,
  getPluginConfigSchema,
  getPluginConfig,
  getPluginConfigRaw,
  updatePluginConfig,
  updatePluginConfigRaw,
  resetPluginConfig,
  togglePlugin,
  type InstalledPlugin,
  type PluginConfigSchema,
  type ConfigFieldSchema,
  type ConfigSectionSchema,
} from '@/lib/plugin-api'

// 字段渲染组件
interface FieldRendererProps {
  field: ConfigFieldSchema
  value: unknown
  onChange: (value: unknown) => void
  sectionName: string
}

function getNestedRecord(config: Record<string, unknown>, path?: string): Record<string, unknown> | undefined {
  if (!path) {
    return undefined
  }
  const parts = path.split('.').filter(Boolean)
  let current: unknown = config

  for (const part of parts) {
    if (!current || typeof current !== 'object' || Array.isArray(current)) {
      return undefined
    }
    current = (current as Record<string, unknown>)[part]
  }

  if (!current || typeof current !== 'object' || Array.isArray(current)) {
    return undefined
  }

  return current as Record<string, unknown>
}

function setNestedField(
  config: Record<string, unknown>,
  path: string,
  fieldName: string,
  value: unknown,
): Record<string, unknown> {
  const parts = path.split('.').filter(Boolean)
  const nextConfig: Record<string, unknown> = { ...config }
  let currentTarget = nextConfig
  let currentSource: Record<string, unknown> | undefined = config

  for (const part of parts) {
    const sourceValue: unknown = currentSource?.[part]
    const nextValue =
      sourceValue && typeof sourceValue === 'object' && !Array.isArray(sourceValue)
        ? { ...(sourceValue as Record<string, unknown>) }
        : {}
    currentTarget[part] = nextValue
    currentTarget = nextValue
    currentSource =
      sourceValue && typeof sourceValue === 'object' && !Array.isArray(sourceValue)
        ? (sourceValue as Record<string, unknown>)
        : undefined
  }

  currentTarget[fieldName] = value
  return nextConfig
}

function FieldRenderer({ field, value, onChange }: FieldRendererProps) {
  const [showPassword, setShowPassword] = useState(false)

  // 根据 ui_type 渲染不同的控件
  switch (field.ui_type) {
    case 'switch':
      return (
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label>{field.label}</Label>
            {field.hint && (
              <p className="text-xs text-muted-foreground">{field.hint}</p>
            )}
          </div>
          <Switch
            checked={Boolean(value ?? field.default)}
            onCheckedChange={onChange}
            disabled={field.disabled}
          />
        </div>
      )

    case 'number':
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <Input
            type="number"
            value={value as number ?? field.default}
            onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
            min={field.min}
            max={field.max}
            step={field.step ?? 1}
            placeholder={field.placeholder}
            disabled={field.disabled}
          />
          {field.hint && (
            <p className="text-xs text-muted-foreground">{field.hint}</p>
          )}
        </div>
      )

    case 'slider':
      return (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>{field.label}</Label>
            <span className="text-sm text-muted-foreground">
              {value as number ?? field.default}
            </span>
          </div>
          <Slider
            value={[value as number ?? field.default as number]}
            onValueChange={(v) => onChange(v[0])}
            min={field.min ?? 0}
            max={field.max ?? 100}
            step={field.step ?? 1}
            disabled={field.disabled}
          />
          {field.hint && (
            <p className="text-xs text-muted-foreground">{field.hint}</p>
          )}
        </div>
      )

    case 'select':
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <Select
            value={String(value ?? field.default)}
            onValueChange={onChange}
            disabled={field.disabled}
          >
            <SelectTrigger>
              <SelectValue placeholder={field.placeholder ?? '请选择'} />
            </SelectTrigger>
            <SelectContent>
              {field.choices?.map((choice) => (
                <SelectItem key={String(choice)} value={String(choice)}>
                  {String(choice)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {field.hint && (
            <p className="text-xs text-muted-foreground">{field.hint}</p>
          )}
        </div>
      )

    case 'textarea':
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <Textarea
            value={value as string ?? field.default}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            rows={field.rows ?? 3}
            disabled={field.disabled}
          />
          {field.hint && (
            <p className="text-xs text-muted-foreground">{field.hint}</p>
          )}
        </div>
      )

    case 'password':
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <div className="relative">
            <Input
              type={showPassword ? 'text' : 'password'}
              value={value as string ?? ''}
              onChange={(e) => onChange(e.target.value)}
              placeholder={field.placeholder}
              disabled={field.disabled}
              className="pr-10"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-0 top-0 h-full px-3"
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </Button>
          </div>
          {field.hint && (
            <p className="text-xs text-muted-foreground">{field.hint}</p>
          )}
        </div>
      )

    case 'list':
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <ListFieldEditor
            value={Array.isArray(value) ? value : (Array.isArray(field.default) ? field.default : [])}
            onChange={(newValue) => onChange(newValue)}
            itemType={field.item_type ?? 'string'}
            itemFields={field.item_fields}
            minItems={field.min_items}
            maxItems={field.max_items}
            disabled={field.disabled}
            placeholder={field.placeholder}
          />
          {field.hint && (
            <p className="text-xs text-muted-foreground">{field.hint}</p>
          )}
        </div>
      )

    case 'text':
    default:
      return (
        <div className="space-y-2">
          <Label>{field.label}</Label>
          <Input
            type="text"
            value={value as string ?? field.default ?? ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            maxLength={field.max_length}
            disabled={field.disabled}
          />
          {field.hint && (
            <p className="text-xs text-muted-foreground">{field.hint}</p>
          )}
        </div>
      )
  }
}

// Section 渲染组件
interface SectionRendererProps {
  sectionName: string
  section: ConfigSectionSchema
  config: Record<string, unknown>
  onChange: (sectionName: string, fieldName: string, value: unknown) => void
}

function SectionRenderer({ sectionName, section, config, onChange }: SectionRendererProps) {
  const [isOpen, setIsOpen] = useState(!section.collapsed)
  const resolvedSectionName = section.name || sectionName
  const sectionConfig = getNestedRecord(config, resolvedSectionName)
  
  // 按 order 排序字段
  const sortedFields = Object.entries(section.fields)
    .filter(([, field]) => !field.hidden)
    .sort(([, a], [, b]) => (a.order ?? 0) - (b.order ?? 0))

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <Card>
        <CollapsibleTrigger asChild>
          <CardHeader className="cursor-pointer hover:bg-muted/50 transition-colors">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {isOpen ? (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                )}
                <CardTitle className="text-lg">{section.title}</CardTitle>
              </div>
              <Badge variant="secondary" className="text-xs">
                {sortedFields.length} 项
              </Badge>
            </div>
            {section.description && (
              <CardDescription className="ml-6">
                {section.description}
              </CardDescription>
            )}
          </CardHeader>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent className="space-y-4 pt-0">
            {sortedFields.map(([fieldName, field]) => (
              <FieldRenderer
                key={fieldName}
                field={field}
                value={sectionConfig?.[fieldName]}
                onChange={(value) => onChange(resolvedSectionName, fieldName, value)}
                sectionName={resolvedSectionName}
              />
            ))}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}

// 插件配置编辑器
interface PluginConfigEditorProps {
  plugin: InstalledPlugin
  onBack: () => void
}

function PluginConfigEditor({ plugin, onBack }: PluginConfigEditorProps) {
  const { toast } = useToast()
  const { triggerRestart, isRestarting } = useRestart()
  const [editMode, setEditMode] = useState<'visual' | 'source'>('visual')
  const [schema, setSchema] = useState<PluginConfigSchema | null>(null)
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [originalConfig, setOriginalConfig] = useState<Record<string, unknown>>({})
  const [sourceCode, setSourceCode] = useState('')
  const [originalSourceCode, setOriginalSourceCode] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [hasTomlError, setHasTomlError] = useState(false)
  const [resetDialogOpen, setResetDialogOpen] = useState(false)

  // 加载配置
  const loadConfig = useCallback(async () => {
    setLoading(true)
    try {
      const [schemaResult, configResult, rawResult] = await Promise.all([
        getPluginConfigSchema(plugin.id),
        getPluginConfig(plugin.id),
        getPluginConfigRaw(plugin.id)
      ])
      
      if (!schemaResult.success) {
        toast({
          title: '加载配置架构失败',
          description: schemaResult.error,
          variant: 'destructive'
        })
        return
      }
      
      if (!configResult.success) {
        toast({
          title: '加载配置数据失败',
          description: configResult.error,
          variant: 'destructive'
        })
        return
      }
      
      if (!rawResult.success) {
        toast({
          title: '加载原始配置失败',
          description: rawResult.error,
          variant: 'destructive'
        })
        return
      }
      
      setSchema(schemaResult.data)
      setConfig(configResult.data)
      setOriginalConfig(JSON.parse(JSON.stringify(configResult.data)))
      setSourceCode(rawResult.data)
      setOriginalSourceCode(rawResult.data)
    } catch (error) {
      toast({
        title: '加载配置失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive'
      })
    } finally {
      setLoading(false)
    }
  }, [plugin.id, toast])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  // 检测配置变化
  useEffect(() => {
    if (editMode === 'visual') {
      setHasChanges(JSON.stringify(config) !== JSON.stringify(originalConfig))
    } else {
      setHasChanges(sourceCode !== originalSourceCode)
    }
  }, [config, originalConfig, sourceCode, originalSourceCode, editMode])

  // 处理字段变化
  const handleFieldChange = (sectionName: string, fieldName: string, value: unknown) => {
    setConfig(prev => setNestedField(prev, sectionName, fieldName, value))
  }

  // 保存配置
  const handleSave = async () => {
    setSaving(true)
    try {
      if (editMode === 'source') {
        // 源代码模式：先验证 TOML 格式
        try {
          parseToml(sourceCode)
        } catch (error) {
          setHasTomlError(true)
          toast({
            title: 'TOML 格式错误',
            description: error instanceof Error ? error.message : '无法解析 TOML 配置，请检查语法',
            variant: 'destructive'
          })
          setSaving(false)
          return
        }
        
        // 格式正确，保存原始配置
        await updatePluginConfigRaw(plugin.id, sourceCode)
        setOriginalSourceCode(sourceCode)
        setHasTomlError(false)
      } else {
        // 可视化模式
        await updatePluginConfig(plugin.id, config)
        setOriginalConfig(JSON.parse(JSON.stringify(config)))
      }
      
      toast({
        title: '配置已保存',
        description: '更改将在插件重新加载后生效'
      })
    } catch (error) {
      toast({
        title: '保存失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive'
      })
    } finally {
      setSaving(false)
    }
  }

  // 重置配置
  const handleReset = async () => {
    try {
      const resetResult = await resetPluginConfig(plugin.id)
      if (!resetResult.success) {
        toast({
          title: '重置失败',
          description: resetResult.error,
          variant: 'destructive'
        })
        return
      }
      toast({
        title: '配置已重置',
        description: '下次加载插件时将使用默认配置'
      })
      setResetDialogOpen(false)
      loadConfig()
    } catch (error) {
      toast({
        title: '重置失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive'
      })
    }
  }

  // 切换启用状态
  const handleToggle = async () => {
    try {
      const toggleResult = await togglePlugin(plugin.id)
      if (!toggleResult.success) {
        toast({
          title: '切换失败',
          description: toggleResult.error,
          variant: 'destructive'
        })
        return
      }
      toast({
        title: toggleResult.data.message,
        description: toggleResult.data.note
      })
      loadConfig()
    } catch (error) {
      toast({
        title: '切换状态失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive'
      })
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!schema) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <AlertCircle className="h-12 w-12 text-muted-foreground" />
        <p className="text-muted-foreground">无法加载配置</p>
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="h-4 w-4 mr-2" />
          返回
        </Button>
      </div>
    )
  }

  // 按 order 排序 sections
  const sortedSections = Object.entries(schema.sections)
    .sort(([, a], [, b]) => (a.order ?? 0) - (b.order ?? 0))

  // 获取当前启用状态
  const isEnabled = (config.plugin as Record<string, unknown>)?.enabled !== false

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* 头部 */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="icon" onClick={onBack}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold">
              {schema.plugin_info.name || plugin.manifest.name}
            </h1>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant={isEnabled ? 'default' : 'secondary'}>
                {isEnabled ? '已启用' : '已禁用'}
              </Badge>
              <span className="text-sm text-muted-foreground">
                v{schema.plugin_info.version || plugin.manifest.version}
              </span>
            </div>
          </div>
        </div>
        <div className="flex gap-2 ml-10 sm:ml-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setEditMode(editMode === 'visual' ? 'source' : 'visual')}
          >
            {editMode === 'visual' ? (
              <>
                <Code2 className="h-4 w-4 mr-2" />
                源代码
              </>
            ) : (
              <>
                <Layout className="h-4 w-4 mr-2" />
                可视化
              </>
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => triggerRestart()}
            disabled={isRestarting}
          >
            <RotateCw className={`h-4 w-4 mr-2 ${isRestarting ? 'animate-spin' : ''}`} />
            重启麦麦
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleToggle}
          >
            <Power className="h-4 w-4 mr-2" />
            {isEnabled ? '禁用' : '启用'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setResetDialogOpen(true)}
          >
            <RotateCcw className="h-4 w-4 mr-2" />
            重置
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={!hasChanges || saving}
          >
            {saving ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-2" />
            )}
            保存
          </Button>
        </div>
      </div>

      {/* 未保存提示 */}
      {hasChanges && (
        <Card className="border-orange-200 bg-orange-50 dark:bg-orange-950/20 dark:border-orange-900">
          <CardContent className="py-3">
            <div className="flex items-center gap-2">
              <Info className="h-4 w-4 text-orange-600" />
              <p className="text-sm text-orange-800 dark:text-orange-200">
                有未保存的更改
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 源代码模式 */}
      {editMode === 'source' && (
        <div className="space-y-4">
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              <strong>源代码模式（高级功能）：</strong>直接编辑 TOML 配置文件。保存时会验证格式，只有格式正确才能保存。
              {hasTomlError && (
                <span className="text-destructive font-semibold ml-2">⚠️ 上次保存失败，请检查 TOML 格式</span>
              )}
            </AlertDescription>
          </Alert>
          
            <CodeEditor
              value={sourceCode}
              onChange={(value) => {
                setSourceCode(value)
                if (hasTomlError) {
                  setHasTomlError(false)
                }
              }}
              language="toml"
              height="calc(100vh - 350px)"
              minHeight="500px"
              placeholder="TOML 配置内容"
            />
        </div>
      )}

      {/* 可视化模式 */}
      {editMode === 'visual' && (
      <>
      {/* 插件未加载提示 */}
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          <strong>提示：</strong>如果插件当前未加载或未启用，WebUI 适配器的高级插件可视化编辑功能可能会不可用。
          请确保插件已启用并成功加载后，再进行配置编辑。
        </AlertDescription>
      </Alert>

      {/* 配置区域 */}
      {schema.layout.type === 'tabs' && schema.layout.tabs.length > 0 ? (
        // 标签页布局
        <Tabs defaultValue={schema.layout.tabs[0]?.id}>
          <TabsList>
            {schema.layout.tabs.map(tab => (
              <TabsTrigger key={tab.id} value={tab.id}>
                {tab.title}
                {tab.badge && (
                  <Badge variant="secondary" className="ml-2 text-xs">
                    {tab.badge}
                  </Badge>
                )}
              </TabsTrigger>
            ))}
          </TabsList>
          {schema.layout.tabs.map(tab => (
            <TabsContent key={tab.id} value={tab.id} className="space-y-4 mt-4">
              {tab.sections.map(sectionName => {
                const section = schema.sections[sectionName]
                if (!section) return null
                return (
                  <SectionRenderer
                    key={sectionName}
                    sectionName={sectionName}
                    section={section}
                    config={config}
                    onChange={handleFieldChange}
                  />
                )
              })}
            </TabsContent>
          ))}
        </Tabs>
      ) : (
        // 自动布局
        <div className="space-y-4">
          {sortedSections.map(([sectionName, section]) => (
            <SectionRenderer
              key={sectionName}
              sectionName={sectionName}
              section={section}
              config={config}
              onChange={handleFieldChange}
            />
          ))}
        </div>
      )}
      </>
      )}

      {/* 重置确认对话框 */}
      <Dialog open={resetDialogOpen} onOpenChange={setResetDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认重置配置</DialogTitle>
            <DialogDescription>
              这将删除当前配置文件，下次加载插件时将使用默认配置。此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetDialogOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={handleReset}>
              确认重置
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// 主页面组件 - 包装 RestartProvider
export function PluginConfigPage() {
  return (
    <RestartProvider>
      <PluginConfigPageContent />
    </RestartProvider>
  )
}

// 内部组件：实际内容
function PluginConfigPageContent() {
  const { toast } = useToast()
  const [plugins, setPlugins] = useState<InstalledPlugin[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPlugin, setSelectedPlugin] = useState<InstalledPlugin | null>(null)

  // 加载插件列表
  const loadPlugins = async () => {
    setLoading(true)
    try {
      const installedResult = await getInstalledPlugins()
      if (!installedResult.success) {
        toast({
          title: '加载插件列表失败',
          description: installedResult.error,
          variant: 'destructive'
        })
        return
      }
      setPlugins(installedResult.data)
    } catch (error) {
      toast({
        title: '加载插件列表失败',
        description: error instanceof Error ? error.message : '未知错误',
        variant: 'destructive'
      })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPlugins()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 过滤插件
  const filteredPlugins = plugins.filter(plugin => {
    const query = searchQuery.toLowerCase()
    return (
      plugin.id.toLowerCase().includes(query) ||
      plugin.manifest.name.toLowerCase().includes(query) ||
      plugin.manifest.description?.toLowerCase().includes(query)
    )
  })
  
  // 去重：如果有重复的 plugin.id，只保留第一个
  const uniqueFilteredPlugins = filteredPlugins.filter((plugin, index, self) =>
    index === self.findIndex((p) => p.id === plugin.id)
  )

  // 统计数据
  const isPluginDisabled = (plugin: InstalledPlugin) => plugin.disabled === true || plugin.enabled === false
  const isPluginLoadSuccess = (plugin: InstalledPlugin) => !isPluginDisabled(plugin) && (
    plugin.load_status === 'success' || plugin.loaded === true
  )
  const isPluginLoadFailed = (plugin: InstalledPlugin) => !isPluginDisabled(plugin) && !isPluginLoadSuccess(plugin)
  const installedCount = plugins.length
  const disabledCount = plugins.filter(isPluginDisabled).length
  const enabledCount = installedCount - disabledCount
  const loadSuccessCount = plugins.filter(isPluginLoadSuccess).length
  const loadFailedCount = plugins.filter(isPluginLoadFailed).length
  const getPluginStatusMeta = (plugin: InstalledPlugin) => {
    if (isPluginDisabled(plugin)) {
      return { dotClassName: 'bg-muted-foreground/45', label: '已禁用' }
    }
    if (isPluginLoadSuccess(plugin)) {
      return { dotClassName: 'bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.16)]', label: '加载成功' }
    }
    return { dotClassName: 'bg-red-500 shadow-[0_0_0_3px_rgba(239,68,68,0.16)]', label: '加载失败' }
  }

  // 如果选中了插件，显示配置编辑器
  if (selectedPlugin) {
    return (
      <>
        <ScrollArea className="h-full">
          <div className="p-4 sm:p-6">
            <PluginConfigEditor
              plugin={selectedPlugin}
              onBack={() => setSelectedPlugin(null)}
            />
          </div>
        </ScrollArea>
        <RestartOverlay />
      </>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="space-y-4 sm:space-y-6 p-4 sm:p-6">
        {/* 标题 */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold">插件配置</h1>
            <p className="text-muted-foreground mt-1 sm:mt-2 text-sm sm:text-base">
              管理和配置已安装的插件
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={loadPlugins}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
        </div>

        {/* 统计信息 */}
        <Card>
          <CardContent className="space-y-3 p-4">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
              <span className="flex items-center gap-2">
                <Package className="h-4 w-4 text-muted-foreground" />
                已安装 <strong>{installedCount}</strong> 个插件
              </span>
              <span>已启用 <strong className="text-emerald-600">{enabledCount}</strong> 个</span>
              <span>已禁用 <strong className="text-muted-foreground">{disabledCount}</strong> 个</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t pt-3 text-sm">
              <span className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                加载成功 <strong className="text-emerald-600">{loadSuccessCount}</strong> 个
              </span>
              <span className="flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-red-600" />
                加载失败 <strong className="text-red-600">{loadFailedCount}</strong> 个
              </span>
            </div>
          </CardContent>
        </Card>

        {/* 搜索框 */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="搜索插件..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>

        {/* 插件列表 */}
        <Card>
          <CardHeader>
            <CardTitle>已安装的插件</CardTitle>
            <CardDescription>点击插件查看和编辑配置</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            ) : uniqueFilteredPlugins.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 space-y-4">
                <Package className="h-16 w-16 text-muted-foreground/50" />
                <div className="text-center space-y-2">
                  <p className="text-lg font-medium text-muted-foreground">
                    {searchQuery ? '没有找到匹配的插件' : '暂无已安装的插件'}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {searchQuery ? '尝试其他搜索关键词' : '前往插件市场安装插件'}
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                {uniqueFilteredPlugins.map(plugin => {
                  const statusMeta = getPluginStatusMeta(plugin)
                  return (
                  <div
                    key={plugin.id}
                    className={`flex items-center justify-between p-4 rounded-lg border hover:bg-muted/50 cursor-pointer transition-colors ${isPluginDisabled(plugin) ? 'opacity-70' : ''}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedPlugin(plugin)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedPlugin(plugin) } }}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span
                        className={`h-2.5 w-2.5 rounded-full flex-shrink-0 ${statusMeta.dotClassName}`}
                        title={statusMeta.label}
                        aria-label={statusMeta.label}
                      />
                      <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                        <Package className="h-5 w-5 text-primary" />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <h3 className="font-medium truncate">
                            {plugin.manifest.name}
                          </h3>
                          <Badge variant="secondary" className="text-xs flex-shrink-0">
                            v{plugin.manifest.version}
                          </Badge>
                        </div>
                        <p className="text-sm text-muted-foreground truncate">
                          {plugin.manifest.description || '暂无描述'}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <Button variant="ghost" size="sm">
                        <Settings className="h-4 w-4" />
                      </Button>
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    </div>
                  </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  )
}
