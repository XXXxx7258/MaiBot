import * as React from 'react'
import * as LucideIcons from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { fieldHooks, type FieldHookRegistry } from '@/lib/field-hooks'
import type { ConfigSchema, FieldSchema } from '@/types/config-schema'

import { DynamicField } from './DynamicField'

export interface DynamicConfigFormProps {
  schema: ConfigSchema
  values: Record<string, unknown>
  onChange: (field: string, value: unknown) => void
  basePath?: string
  hooks?: FieldHookRegistry
  /** 嵌套层级：0 = tab 内容层，1 = section 内容层，2+ = 更深嵌套 */
  level?: number
  advancedVisible?: boolean
  sectionColumns?: 1 | 2
}

function buildFieldPath(basePath: string, fieldName: string) {
  return basePath ? `${basePath}.${fieldName}` : fieldName
}

function resolveSectionTitle(schema: ConfigSchema) {
  return schema.uiLabel || schema.classDoc || schema.className
}

function SectionIcon({ iconName }: { iconName?: string }) {
  if (!iconName) return null
  const IconComponent = LucideIcons[iconName as keyof typeof LucideIcons] as
    | React.ComponentType<{ className?: string }>
    | undefined
  if (!IconComponent) return null
  return <IconComponent className="h-5 w-5 text-muted-foreground" />
}

export function AdvancedSettingsButton({
  active,
  onClick,
}: {
  active: boolean
  onClick: () => void
}) {
  return (
    <Button
      type="button"
      variant={active ? 'default' : 'outline'}
      size="sm"
      onClick={onClick}
    >
      高级设置
    </Button>
  )
}

function DynamicConfigSection({
  advancedVisible,
  basePath,
  hooks,
  level,
  nestedSchema,
  onChange,
  sectionKey,
  sectionTitle,
  values,
}: {
  advancedVisible: boolean
  basePath: string
  hooks: FieldHookRegistry
  level: number
  nestedSchema: ConfigSchema
  onChange: (field: string, value: unknown) => void
  sectionKey: string
  sectionTitle: string
  values: Record<string, unknown>
}) {
  return (
    <Card className="min-w-0">
      <CardHeader className="border-b border-border/50 pb-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <SectionIcon iconName={nestedSchema.uiIcon} />
              <CardTitle className="text-lg text-primary">{sectionTitle}</CardTitle>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-4">
        <DynamicConfigForm
          schema={nestedSchema}
          values={values}
          onChange={(field, value) => onChange(`${sectionKey}.${field}`, value)}
          basePath={basePath}
          hooks={hooks}
          level={level}
          advancedVisible={advancedVisible}
          sectionColumns={1}
        />
      </CardContent>
    </Card>
  )
}

/**
 * DynamicConfigForm - 动态配置表单组件
 *
 * 根据 ConfigSchema 渲染表单字段，支持：
 * 1. Hook 系统：通过 FieldHookRegistry 自定义字段渲染
 *    - replace 模式：完全替换默认渲染
 *    - wrapper 模式：包装默认渲染（通过 children 传递）
 * 2. 嵌套 schema：递归渲染 schema.nested 中的子配置
 * 3. 高级设置：由栏目标题右侧按钮控制显示
 */
export const DynamicConfigForm: React.FC<DynamicConfigFormProps> = ({
  schema,
  values,
  onChange,
  basePath = '',
  hooks = fieldHooks,
  level = 0,
  advancedVisible,
  sectionColumns = 1,
}) => {
  const resolvedAdvancedVisible = advancedVisible ?? false

  const fieldMap = React.useMemo(
    () => new Map(schema.fields.map((field) => [field.name, field])),
    [schema.fields],
  )

  const renderField = (field: FieldSchema) => {
    const fieldPath = buildFieldPath(basePath, field.name)
    const nestedSchema = schema.nested?.[field.name]

    if (hooks.has(fieldPath)) {
      const hookEntry = hooks.get(fieldPath)
      if (!hookEntry) return null
      if (hookEntry.type === 'hidden') return null

      const HookComponent = hookEntry.component

      if (hookEntry.type === 'replace') {
        return (
          <HookComponent
            fieldPath={fieldPath}
            value={values[field.name]}
            onChange={(v) => onChange(field.name, v)}
            onParentChange={onChange}
            schema={field}
            nestedSchema={nestedSchema}
            parentValues={values}
          />
        )
      }

      return (
        <HookComponent
          fieldPath={fieldPath}
          value={values[field.name]}
          onChange={(v) => onChange(field.name, v)}
          onParentChange={onChange}
          schema={field}
          nestedSchema={nestedSchema}
          parentValues={values}
        >
          <DynamicField
            schema={field}
            value={values[field.name]}
            onChange={(v) => onChange(field.name, v)}
            fieldPath={fieldPath}
          />
        </HookComponent>
      )
    }

    return (
      <DynamicField
        schema={field}
        value={values[field.name]}
        onChange={(v) => onChange(field.name, v)}
        fieldPath={fieldPath}
      />
    )
  }

  const shouldRenderFieldInline = (field: FieldSchema) => {
    const fieldPath = buildFieldPath(basePath, field.name)
    if (hooks.get(fieldPath)?.type === 'hidden') {
      return false
    }

    if (!schema.nested?.[field.name]) {
      return true
    }

    return hooks.get(fieldPath)?.type === 'replace'
  }

  const schemaHasVisibleContent = React.useCallback(
    (targetSchema: ConfigSchema, targetBasePath: string): boolean => {
      const targetFields = targetSchema.fields ?? []
      const hasVisibleInlineField = targetFields.some((field) => {
        const fieldPath = buildFieldPath(targetBasePath, field.name)
        const hookEntry = hooks.get(fieldPath)

        if (hookEntry?.type === 'hidden') {
          return false
        }

        if (targetSchema.nested?.[field.name] && hookEntry?.type !== 'replace') {
          return false
        }

        return resolvedAdvancedVisible || !field.advanced
      })

      if (hasVisibleInlineField) {
        return true
      }

      return Object.entries(targetSchema.nested ?? {}).some(([key, nestedSchema]) => {
        const nestedField = targetFields.find((field) => field.name === key)
        const nestedFieldPath = buildFieldPath(targetBasePath, key)
        const hookEntry = hooks.get(nestedFieldPath)

        if (hookEntry?.type === 'hidden') {
          return false
        }

        if (nestedField?.advanced && !resolvedAdvancedVisible) {
          return false
        }

        if (hookEntry?.type === 'replace') {
          return true
        }

        return schemaHasVisibleContent(nestedSchema, nestedFieldPath)
      })
    },
    [hooks, resolvedAdvancedVisible],
  )

  const inlineFields = schema.fields.filter(shouldRenderFieldInline)
  const inlineNestedFieldNames = new Set(
    inlineFields
      .filter((field) => Boolean(schema.nested?.[field.name]))
      .map((field) => field.name),
  )
  const normalFields = inlineFields.filter((field) => !field.advanced)
  const visibleFields = resolvedAdvancedVisible
    ? inlineFields
    : normalFields

  const groupFieldsByRow = (fields: FieldSchema[]) => {
    const rows: FieldSchema[][] = []
    let currentRow: FieldSchema[] = []
    let currentRowKey: string | undefined

    for (const field of fields) {
      const rowKey = field['x-row']
      if (rowKey && rowKey === currentRowKey) {
        currentRow.push(field)
        continue
      }

      if (currentRow.length > 0) {
        rows.push(currentRow)
      }

      currentRow = [field]
      currentRowKey = rowKey
    }

    if (currentRow.length > 0) {
      rows.push(currentRow)
    }

    return rows
  }

  const renderRows = (rows: FieldSchema[][]) => (
    <>
      {rows.map((row) => (
        row.length > 1 ? (
          <div
            key={row.map((field) => field.name).join('|')}
            className="grid min-w-0 gap-4 py-1 md:grid-cols-[repeat(var(--field-row-count),minmax(0,1fr))]"
            style={{ '--field-row-count': row.length } as React.CSSProperties}
          >
            {row.map((field) => (
              <div key={field.name} className="min-w-0">{renderField(field)}</div>
            ))}
          </div>
        ) : (
          <div key={row[0].name} className="min-w-0 py-1">{renderField(row[0])}</div>
        )
      ))}
    </>
  )

  const renderFieldList = (fields: FieldSchema[]) => (
    <>
      {groupFieldsByRow(fields).map((row, index) => (
        <React.Fragment key={row.map((field) => field.name).join('|')}>
          {index > 0 && <Separator className="my-2 bg-border/50" />}
          {renderRows([row])}
        </React.Fragment>
      ))}
    </>
  )

  return (
    <div className="min-w-0 space-y-6">
      {visibleFields.length > 0 && (
        <div>
          {renderFieldList(visibleFields)}
        </div>
      )}

      {schema.nested &&
        (() => {
          const nestedSections = Object.entries(schema.nested)
          .filter(([key]) => !inlineNestedFieldNames.has(key))
          .map(([key, nestedSchema]) => {
          const nestedField = fieldMap.get(key)
          const nestedFieldPath = buildFieldPath(basePath, key)

          if (hooks.has(nestedFieldPath)) {
            const hookEntry = hooks.get(nestedFieldPath)
            if (!hookEntry) return null
            if (hookEntry.type === 'hidden') return null
            if (nestedField?.advanced && !resolvedAdvancedVisible) return null
            if (
              hookEntry.type !== 'replace' &&
              nestedSchema &&
              !schemaHasVisibleContent(nestedSchema, nestedFieldPath)
            ) {
              return null
            }

            const HookComponent = hookEntry.component
            if (hookEntry.type === 'replace') {
              return (
                <div key={key} className="min-w-0">
                  <HookComponent
                    fieldPath={nestedFieldPath}
                    value={values[key]}
                      onChange={(v) => onChange(key, v)}
                      onParentChange={onChange}
                      schema={nestedField ?? nestedSchema}
                    nestedSchema={nestedSchema}
                    parentValues={values}
                  />
                </div>
              )
            }

            return (
              <div key={key} className="min-w-0">
                <HookComponent
                  fieldPath={nestedFieldPath}
                  value={values[key]}
                  onChange={(v) => onChange(key, v)}
                  onParentChange={onChange}
                  schema={nestedField ?? nestedSchema}
                  nestedSchema={nestedSchema}
                  parentValues={values}
                >
                  <DynamicConfigForm
                    schema={nestedSchema}
                    values={(values[key] as Record<string, unknown>) || {}}
                    onChange={(field, value) => onChange(`${key}.${field}`, value)}
                    basePath={nestedFieldPath}
                    hooks={hooks}
                    level={level + 1}
                    advancedVisible={resolvedAdvancedVisible}
                    sectionColumns={1}
                  />
                </HookComponent>
              </div>
            )
          }

          const sectionTitle = resolveSectionTitle(nestedSchema)
          if (!schemaHasVisibleContent(nestedSchema, nestedFieldPath)) {
            return null
          }

          if (level === 0) {
            return (
              <DynamicConfigSection
                key={key}
                advancedVisible={resolvedAdvancedVisible}
                nestedSchema={nestedSchema}
                values={(values[key] as Record<string, unknown>) || {}}
                onChange={onChange}
                basePath={nestedFieldPath}
                hooks={hooks}
                level={level + 1}
                sectionKey={key}
                sectionTitle={sectionTitle}
              />
            )
          }

          return (
            <Card key={key} className="min-w-0 border-border/70 bg-muted/20 shadow-none">
              <CardHeader className="border-b border-border/50 px-4 py-3">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <SectionIcon iconName={nestedSchema.uiIcon} />
                      <CardTitle className="text-sm text-primary">{sectionTitle}</CardTitle>
                    </div>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="px-4 pb-4 pt-4">
                <DynamicConfigForm
                  schema={nestedSchema}
                  values={(values[key] as Record<string, unknown>) || {}}
                  onChange={(field, value) => onChange(`${key}.${field}`, value)}
                  basePath={nestedFieldPath}
                  hooks={hooks}
                  level={level + 1}
                  advancedVisible={resolvedAdvancedVisible}
                  sectionColumns={1}
                />
              </CardContent>
            </Card>
          )
        })

          const visibleNestedSections = nestedSections.filter(
            (section): section is React.ReactElement => Boolean(section),
          )

          if (level === 0 && sectionColumns === 2 && visibleNestedSections.length > 1) {
            return (
              <div className="grid min-w-0 gap-4 md:grid-cols-2">
                {visibleNestedSections}
              </div>
            )
          }

          return visibleNestedSections
        })()}
    </div>
  )
}
