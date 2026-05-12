import { describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'

import { MultipleReplyStyleHook } from '../complexFieldHooks'
import { createJsonFieldHook } from '../JsonFieldHookFactory'
import { createListItemEditorHook } from '../ListItemEditorHookFactory'
import type { FieldSchema } from '@/types/config-schema'

const advancedSchema: FieldSchema = {
  name: 'advanced_field',
  type: 'array',
  label: 'Advanced field',
  description: 'Advanced field description',
  required: false,
  advanced: true,
}

describe('custom bot config hooks', () => {
  it('colors string-list hook titles for advanced fields', () => {
    const { container } = render(
      <MultipleReplyStyleHook
        fieldPath="personality.multiple_reply_style"
        onChange={vi.fn()}
        schema={advancedSchema}
        value={[]}
      />,
    )

    expect(container.querySelector('label')).toHaveClass('text-sky-700')
  })

  it('colors list-editor hook titles for advanced fields', () => {
    const ListHook = createListItemEditorHook({ addLabel: 'Add item' })

    const { getByText } = render(
      <ListHook
        fieldPath="advanced.items"
        onChange={vi.fn()}
        schema={advancedSchema}
        nestedSchema={{
          className: 'AdvancedItem',
          classDoc: 'Advanced item',
          fields: [],
        }}
        value={[]}
      />,
    )

    expect(getByText('Advanced field')).toHaveClass('text-sky-700')
  })

  it('colors JSON hook titles for advanced fields', () => {
    const JsonHook = createJsonFieldHook({
      emptyValue: [],
      helperText: 'Edit JSON.',
      placeholder: '[]',
    })

    const { getByText } = render(
      <JsonHook
        fieldPath="advanced.json"
        onChange={vi.fn()}
        schema={advancedSchema}
        value={[]}
      />,
    )

    expect(getByText('Advanced field')).toHaveClass('text-sky-700')
  })
})
