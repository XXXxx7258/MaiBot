import { Plus, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { FieldHookComponent } from '@/lib/field-hooks'

import { createJsonFieldHook } from './JsonFieldHookFactory'
import { createListItemEditorHook } from './ListItemEditorHookFactory'

type ExpressionRuleType = 'group' | 'private'

interface ExpressionGroupTarget {
  platform: string
  item_id: string
  type: ExpressionRuleType
}

interface ExpressionGroupValue {
  targets: ExpressionGroupTarget[]
}

interface PlatformAccountRow {
  platform: string
  account: string
}

const ruleTypeLabel = (rule: unknown) => {
  if (rule === 'private') return '私聊'
  if (rule === 'group') return '群聊'
  return rule ? String(rule) : '未指定'
}

const platformLabel = (item: Record<string, unknown>) => {
  const platform = typeof item.platform === 'string' ? item.platform.trim() : ''
  const itemId = typeof item.item_id === 'string' ? item.item_id.trim() : ''
  if (!platform && !itemId) return '全局'
  if (!platform) return itemId
  if (!itemId) return platform
  return `${platform}:${itemId}`
}

const truncate = (text: string, max = 32) => {
  if (text.length <= max) return text
  return `${text.slice(0, max)}…`
}

const collectStringList = (value: unknown): string[] => {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter((item) => item.length > 0)
}

const normalizeExpressionRuleType = (value: unknown): ExpressionRuleType => {
  return value === 'private' ? 'private' : 'group'
}

const normalizeExpressionTarget = (value: unknown): ExpressionGroupTarget => {
  const source =
    value && typeof value === 'object'
      ? (value as Record<string, unknown>)
      : {}
  return {
    platform:
      typeof source.platform === 'string' ? source.platform.trim() : 'qq',
    item_id:
      typeof source.item_id === 'string' ? source.item_id.trim() : '',
    type: normalizeExpressionRuleType(source.type ?? source.rule_type),
  }
}

const normalizeExpressionGroups = (value: unknown): ExpressionGroupValue[] => {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    const source =
      item && typeof item === 'object'
        ? (item as Record<string, unknown>)
        : {}
    let rawMembers: unknown[] = []
    if (Array.isArray(source.targets)) {
      rawMembers = source.targets
    } else if (Array.isArray(source.expression_groups)) {
      rawMembers = source.expression_groups
    } else if (Array.isArray(source.jargon_groups)) {
      rawMembers = source.jargon_groups
    }
    const members = rawMembers.map(normalizeExpressionTarget)
    return { targets: members }
  })
}

const createExpressionTarget = (): ExpressionGroupTarget => ({
  platform: 'qq',
  item_id: '',
  type: 'group',
})

const formatExpressionTarget = (target: ExpressionGroupTarget): string => {
  const platform = target.platform.trim()
  const itemId = target.item_id.trim()
  const rule = ruleTypeLabel(target.type)
  if (!platform && !itemId) return `全局 · ${rule}`
  if (!itemId) return `${platform} · ${rule}`
  return `${platform}:${itemId} · ${rule}`
}

const normalizePlatformAccounts = (value: unknown): string[] => {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item ?? ''))
}

const parsePlatformAccount = (value: string): PlatformAccountRow => {
  const separatorIndex = value.indexOf(':')
  if (separatorIndex < 0) {
    return { platform: '', account: value }
  }
  return {
    platform: value.slice(0, separatorIndex),
    account: value.slice(separatorIndex + 1),
  }
}

const formatPlatformAccount = (row: PlatformAccountRow): string => {
  const platform = row.platform.trim()
  const account = row.account.trim()
  if (!platform) return account
  if (!account) return `${platform}:`
  return `${platform}:${account}`
}

interface StringListHookOptions {
  addLabel: string
  emptyText: string
  label: string
  multiline?: boolean
  placeholder?: string
}

function createStringListHook(options: StringListHookOptions): FieldHookComponent {
  return ({ onChange, value }) => {
    const items = Array.isArray(value) ? value.map((item) => String(item ?? '')) : []

    const updateItems = (nextItems: string[]) => {
      onChange?.(nextItems)
    }

    const addItem = () => {
      updateItems([...items, ''])
    }

    const removeItem = (itemIndex: number) => {
      updateItems(items.filter((_, index) => index !== itemIndex))
    }

    const updateItem = (itemIndex: number, nextValue: string) => {
      updateItems(items.map((item, index) => (index === itemIndex ? nextValue : item)))
    }

    const InputComponent = options.multiline ? Textarea : Input

    return (
      <div className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <Label className="text-[15px] leading-6">{options.label}</Label>
          <Button type="button" size="sm" variant="outline" onClick={addItem}>
            <Plus className="mr-2 h-4 w-4" />
            {options.addLabel}
          </Button>
        </div>

        {items.length === 0 ? (
          <div className="rounded-md border border-dashed bg-muted/30 px-4 py-5 text-center text-sm text-muted-foreground">
            {options.emptyText}
          </div>
        ) : (
          <div className="space-y-2">
            {items.map((item, itemIndex) => (
              <div
                key={itemIndex}
                className="grid gap-2 rounded-md border bg-muted/20 p-3 sm:grid-cols-[minmax(0,1fr)_2.5rem]"
              >
                <InputComponent
                  value={item}
                  placeholder={options.placeholder}
                  onChange={(event) => updateItem(itemIndex, event.target.value)}
                  {...(options.multiline ? { rows: 2 } : {})}
                />
                <div className="flex items-start justify-end">
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`删除${options.label} ${itemIndex + 1}`}
                    onClick={() => removeItem(itemIndex)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }
}

export const AliasNamesHook = createStringListHook({
  addLabel: '添加别名',
  emptyText: '暂无别名。',
  label: '别名',
  placeholder: '小麦',
})

export const MultipleReplyStyleHook = createStringListHook({
  addLabel: '添加表达风格',
  emptyText: '暂无备用表达风格。',
  label: '备用表达风格',
  multiline: true,
  placeholder: '输入一种备用表达风格',
})

export const ChatTalkValueRulesHook = createListItemEditorHook({
  addLabel: '添加发言频率规则',
  addButtonPlacement: 'top',
  collapseWhen: ({ parentValues }) => parentValues?.enable_talk_value_rules === false,
  collapsedText: '动态发言频率规则未启用，规则列表已折叠。展开后仍可查看或编辑已有规则。',
  expandLabel: '展开规则',
  collapseLabel: '折叠规则',
  helperText: '可按平台/聊天流/时段分别配置发言频率，留空表示全局。',
  emptyText: '尚未配置任何规则，将使用全局默认频率。',
  collapseButtonDisplay: 'icon',
  fieldRows: [
    ['platform', 'item_id', 'rule_type'],
    ['time', 'value'],
  ],
  itemTitle: (item) => {
    const time =
      typeof item.time === 'string' && item.time.trim()
        ? item.time.trim()
        : '全天'
    const value =
      typeof item.value === 'number' ? item.value.toFixed(2) : '—'
    return `${platformLabel(item)} · ${ruleTypeLabel(item.rule_type)} · ${time} · 频率 ${value}`
  },
})

export const ChatPromptsHook = createListItemEditorHook({
  addLabel: '添加额外 Prompt',
  helperText: '为指定平台和聊天流添加额外提示。platform、item_id 和 prompt 同时留空时表示空条目；填写任意一项后这三项都需要填写。',
  emptyText: '尚未配置任何聊天额外 Prompt。',
  addButtonPlacement: 'top',
  fieldRows: [['platform', 'item_id', 'rule_type']],
  fieldSchemaOverrides: {
    item_id: {
      'x-input-width': '8rem',
      'x-layout': 'inline-right',
    },
    platform: {
      'x-input-width': '8rem',
      'x-layout': 'inline-right',
    },
    prompt: {
      'x-textarea-min-height': 38,
      'x-textarea-rows': 1,
    },
    rule_type: {
      'x-input-width': '8rem',
      'x-layout': 'inline-right',
    },
  },
  iconName: 'file-text',
  itemTitle: (item) => {
    const prompt = typeof item.prompt === 'string' ? item.prompt.trim() : ''
    return `${platformLabel(item)} · ${ruleTypeLabel(item.rule_type)} · ${prompt ? truncate(prompt) : '未填写 Prompt'}`
  },
})

export const ExpressionLearningListHook = createListItemEditorHook({
  addLabel: '添加学习规则',
  helperText: '为不同聊天流单独配置是否使用和学习。platform 或 item_id 可以填 * 作为通配符。',
  emptyText: '尚未配置任何学习规则。',
  fieldRows: [
    ['platform', 'item_id', 'type'],
    ['use', 'learn'],
  ],
  itemTitle: (item) => {
    const flags: string[] = []
    if (item.use) flags.push('使用')
    if (item.learn) flags.push('学习')
    const flagText = flags.length ? flags.join(' / ') : '使用和学习均关闭'
    return `${platformLabel(item)} · ${ruleTypeLabel(item.type)} · ${flagText}`
  },
})

export const JargonLearningListHook = ExpressionLearningListHook

export const BotPlatformsHook: FieldHookComponent = ({ onChange, value }) => {
  const platforms = normalizePlatformAccounts(value)
  const rows = platforms.map(parsePlatformAccount)

  const updateRows = (nextRows: PlatformAccountRow[]) => {
    onChange?.(nextRows.map(formatPlatformAccount))
  }

  const addRow = () => {
    updateRows([...rows, { platform: '', account: '' }])
  }

  const removeRow = (rowIndex: number) => {
    updateRows(rows.filter((_, index) => index !== rowIndex))
  }

  const updateRow = (rowIndex: number, patch: Partial<PlatformAccountRow>) => {
    updateRows(
      rows.map((row, index) =>
        index === rowIndex ? { ...row, ...patch } : row
      )
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <Label className="text-sm font-medium">其他平台</Label>
          <p className="text-xs text-muted-foreground">
            每行保存为 platform:account，例如 wx:114514。
          </p>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={addRow}>
          <Plus className="mr-2 h-4 w-4" />
          添加平台
        </Button>
      </div>

      {rows.length === 0 ? (
        <div className="rounded-md border border-dashed bg-muted/30 px-4 py-5 text-center text-sm text-muted-foreground">
          暂无其他平台账号。
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map((row, rowIndex) => (
            <div
              key={rowIndex}
              className="grid gap-2 rounded-md border bg-muted/20 p-3 sm:grid-cols-[minmax(7rem,0.6fr)_minmax(10rem,1fr)_auto]"
            >
              <div className="space-y-1">
                <Label className="text-xs">平台</Label>
                <Input
                  value={row.platform}
                  placeholder="wx"
                  onChange={(event) =>
                    updateRow(rowIndex, { platform: event.target.value })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">账号</Label>
                <Input
                  className="font-mono"
                  value={row.account}
                  placeholder="114514"
                  onChange={(event) =>
                    updateRow(rowIndex, { account: event.target.value })
                  }
                />
              </div>
              <div className="flex items-end justify-end">
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={`删除其他平台 ${rowIndex + 1}`}
                  onClick={() => removeRow(rowIndex)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export const HiddenFieldHook: FieldHookComponent = () => null

export const BotPlatformAccountsHook: FieldHookComponent = ({
  onChange,
  onParentChange,
  parentValues,
  value,
}) => {
  const primaryPlatform = typeof value === 'string' ? value : ''
  const qqAccountValue = parentValues?.qq_account
  const qqAccount =
    typeof qqAccountValue === 'string' || typeof qqAccountValue === 'number'
      ? String(qqAccountValue)
      : ''
  const platforms = normalizePlatformAccounts(parentValues?.platforms)
  const rows = platforms.map(parsePlatformAccount)

  const updateRows = (nextRows: PlatformAccountRow[]) => {
    onParentChange?.('platforms', nextRows.map(formatPlatformAccount))
  }

  const addRow = () => {
    updateRows([...rows, { platform: '', account: '' }])
  }

  const removeRow = (rowIndex: number) => {
    updateRows(rows.filter((_, index) => index !== rowIndex))
  }

  const updateRow = (rowIndex: number, patch: Partial<PlatformAccountRow>) => {
    updateRows(rows.map((row, index) => (index === rowIndex ? { ...row, ...patch } : row)))
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <Label className="text-[15px] font-semibold leading-6">平台账号</Label>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={addRow}>
          <Plus className="mr-2 h-4 w-4" />
          添加平台
        </Button>
      </div>

      <div className="space-y-2">
        <div className="grid gap-2 rounded-md border bg-muted/20 p-3 sm:grid-cols-[minmax(7rem,0.6fr)_minmax(10rem,1fr)_2.5rem]">
          <div className="space-y-1">
            <Label className="text-xs">平台</Label>
            <Input
              value={primaryPlatform}
              placeholder="qq"
              onChange={(event) => onChange?.(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">账号</Label>
            <Input
              className="font-mono"
              value={qqAccount}
              placeholder="2814567326"
              onChange={(event) => onParentChange?.('qq_account', event.target.value)}
            />
          </div>
          <div className="flex items-end justify-end">
            <span className="rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
              主
            </span>
          </div>
        </div>

        {rows.map((row, rowIndex) => (
          <div
            key={rowIndex}
            className="grid gap-2 rounded-md border bg-muted/20 p-3 sm:grid-cols-[minmax(7rem,0.6fr)_minmax(10rem,1fr)_2.5rem]"
          >
            <div className="space-y-1">
              <Label className="text-xs">平台</Label>
              <Input
                value={row.platform}
                placeholder="wx"
                onChange={(event) => updateRow(rowIndex, { platform: event.target.value })}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">账号</Label>
              <Input
                className="font-mono"
                value={row.account}
                placeholder="114514"
                onChange={(event) => updateRow(rowIndex, { account: event.target.value })}
              />
            </div>
            <div className="flex items-end justify-end">
              <Button
                type="button"
                size="icon"
                variant="ghost"
                aria-label={`删除其他平台 ${rowIndex + 1}`}
                onClick={() => removeRow(rowIndex)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export const KeywordRulesHook = createListItemEditorHook({
  addLabel: '添加关键词规则',
  helperText: '匹配命中后会用 reaction 内容作为额外上下文。keywords 至少填一条，或使用正则模式。',
  emptyText: '尚未添加任何关键词规则。',
  itemTitle: (item) => {
    const keywords = collectStringList(item.keywords)
    const regex = collectStringList(item.regex)
    const reaction =
      typeof item.reaction === 'string' ? item.reaction.trim() : ''
    const left = keywords.length
      ? `关键词 ${keywords.length} 条`
      : regex.length
        ? `正则 ${regex.length} 条`
        : '未配置匹配项'
    const right = reaction ? `→ ${truncate(reaction)}` : '→ 未填写反应'
    return `${left} ${right}`
  },
})

export const RegexRulesHook = createListItemEditorHook({
  addLabel: '添加正则规则',
  helperText: '正则模式按 Python 语法编写，命中时把 reaction 作为提示注入。',
  emptyText: '尚未添加任何正则规则。',
  itemTitle: (item) => {
    const regex = collectStringList(item.regex)
    const keywords = collectStringList(item.keywords)
    const reaction =
      typeof item.reaction === 'string' ? item.reaction.trim() : ''
    const left = regex.length
      ? `正则 ${regex.length} 条`
      : keywords.length
        ? `关键词 ${keywords.length} 条`
        : '未配置匹配项'
    const right = reaction ? `→ ${truncate(reaction)}` : '→ 未填写反应'
    return `${left} ${right}`
  },
})

export const ExpressionGroupsHook: FieldHookComponent = ({ fieldPath, onChange, value }) => {
  const groups = normalizeExpressionGroups(value)
  const isJargonGroup = fieldPath?.includes('jargon') ?? false
  const groupLabel = isJargonGroup ? '黑话互通组' : '表达互通组'
  const learnedContentLabel = isJargonGroup ? '黑话' : '表达方式'

  const updateGroups = (nextGroups: ExpressionGroupValue[]) => {
    onChange?.(nextGroups)
  }

  const addGroup = () => {
    updateGroups([...groups, { targets: [] }])
  }

  const removeGroup = (groupIndex: number) => {
    updateGroups(groups.filter((_, index) => index !== groupIndex))
  }

  const addMember = (groupIndex: number) => {
    updateGroups(
      groups.map((group, index) =>
        index === groupIndex
          ? {
              targets: [
                ...group.targets,
                createExpressionTarget(),
              ],
            }
          : group
      )
    )
  }

  const removeMember = (groupIndex: number, memberIndex: number) => {
    updateGroups(
      groups.map((group, index) =>
        index === groupIndex
          ? {
              targets: group.targets.filter(
                (_, currentMemberIndex) => currentMemberIndex !== memberIndex
              ),
            }
          : group
      )
    )
  }

  const updateMember = (
    groupIndex: number,
    memberIndex: number,
    patch: Partial<ExpressionGroupTarget>
  ) => {
    updateGroups(
      groups.map((group, index) =>
        index === groupIndex
          ? {
              targets: group.targets.map(
                (member, currentMemberIndex) =>
                  currentMemberIndex === memberIndex
                    ? { ...member, ...patch }
                    : member
              ),
            }
          : group
      )
    )
  }

  return (
    <div className="space-y-3 rounded-lg border bg-card p-4 sm:p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <h3 className="text-base font-semibold">{groupLabel}</h3>
          <p className="text-sm text-muted-foreground">
            每个互通组内的聊天流会共享已学习的{learnedContentLabel}。成员会保存为
            targets 数组结构。
          </p>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={addGroup}>
          <Plus className="mr-2 h-4 w-4" />
          添加{groupLabel}
        </Button>
      </div>

      {groups.length === 0 ? (
        <div className="rounded-md border border-dashed bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
          暂无{groupLabel}，点击上方按钮开始配置。
        </div>
      ) : (
        <div className="space-y-2">
          {groups.map((group, groupIndex) => (
            <div
              key={groupIndex}
              className="space-y-2 rounded-md border bg-muted/20 p-2.5 sm:p-3"
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">
                    {groupLabel} {groupIndex + 1}
                  </span>
                  <Badge variant="secondary">
                    {group.targets.length} 个成员
                  </Badge>
                </div>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => addMember(groupIndex)}
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    添加成员
                  </Button>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`删除互通组 ${groupIndex + 1}`}
                    onClick={() => removeGroup(groupIndex)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              {group.targets.length === 0 ? (
                <div className="rounded-md bg-background/70 px-3 py-4 text-sm text-muted-foreground">
                  这个互通组还没有成员。
                </div>
              ) : (
                <div className="space-y-1.5">
                  {group.targets.map((member, memberIndex) => (
                    <div
                      key={`${groupIndex}-${memberIndex}`}
                      className="grid items-end gap-2 rounded-md bg-background/80 px-2.5 py-2 md:grid-cols-[minmax(6rem,0.65fr)_minmax(9rem,1fr)_minmax(7rem,0.75fr)_2.25rem]"
                    >
                      <div className="space-y-0.5">
                        <Label className="text-[11px] leading-none text-muted-foreground">平台</Label>
                        <Input
                          className="h-8"
                          value={member.platform}
                          placeholder="qq"
                          onChange={(event) =>
                            updateMember(groupIndex, memberIndex, {
                              platform: event.target.value,
                            })
                          }
                        />
                      </div>
                      <div className="space-y-0.5">
                        <Label className="text-[11px] leading-none text-muted-foreground">账号 / 群号</Label>
                        <Input
                          className="h-8 font-mono"
                          value={member.item_id}
                          placeholder="123456"
                          onChange={(event) =>
                            updateMember(groupIndex, memberIndex, {
                              item_id: event.target.value,
                            })
                          }
                        />
                      </div>
                      <div className="space-y-0.5">
                        <Label className="text-[11px] leading-none text-muted-foreground">类型</Label>
                        <Select
                          value={member.type}
                          onValueChange={(nextRuleType) =>
                            updateMember(groupIndex, memberIndex, {
                              type: normalizeExpressionRuleType(nextRuleType),
                            })
                          }
                        >
                          <SelectTrigger className="h-8">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="group">群聊</SelectItem>
                            <SelectItem value="private">私聊</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="flex items-end justify-between gap-2 md:justify-end">
                        <span className="min-w-0 truncate text-xs text-muted-foreground md:hidden">
                          {formatExpressionTarget(member)}
                        </span>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="h-8 w-8"
                          aria-label={`删除互通组 ${groupIndex + 1} 的成员 ${memberIndex + 1}`}
                          onClick={() => removeMember(groupIndex, memberIndex)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export const JargonGroupsHook = ExpressionGroupsHook

export const MCPRootItemsHook = createJsonFieldHook({
  emptyValue: [],
  helperText: 'MCP Roots 条目为对象数组，使用 JSON 编辑。',
  placeholder: '[\n  {\n    "enabled": true,\n    "uri": "file:///Users/example/project",\n    "name": "project-root"\n  }\n]',
})

export const MCPServersHook = createJsonFieldHook({
  emptyValue: [],
  helperText: 'MCP 服务器配置结构较复杂，使用 JSON 编辑。',
  placeholder: '[\n  {\n    "name": "example-server",\n    "enabled": true,\n    "transport": "stdio",\n    "command": "uvx",\n    "args": ["example-server"],\n    "env": {},\n    "url": "",\n    "headers": {},\n    "http_timeout_seconds": 30.0,\n    "read_timeout_seconds": 300.0,\n    "authorization": {\n      "mode": "none",\n      "bearer_token": ""\n    }\n  }\n]',
})
