type ApiErrorDetail = {
  loc?: unknown
  msg?: unknown
  message?: unknown
  type?: unknown
}

function formatLocation(loc: unknown): string {
  if (Array.isArray(loc)) {
    return loc.map((item) => String(item)).join('.')
  }
  if (loc === null || loc === undefined || loc === '') {
    return ''
  }
  return String(loc)
}

function formatDetailItem(item: unknown): string {
  if (typeof item === 'string') {
    return item
  }

  if (item && typeof item === 'object') {
    const detail = item as ApiErrorDetail
    const message = detail.msg ?? detail.message
    const location = formatLocation(detail.loc)
    if (message !== null && message !== undefined && message !== '') {
      return location ? `${location}: ${String(message)}` : String(message)
    }
  }

  try {
    return JSON.stringify(item)
  } catch {
    return String(item)
  }
}

export function formatApiError(errorData: unknown, fallback: string): string {
  if (!errorData) {
    return fallback
  }

  if (typeof errorData === 'string') {
    return errorData || fallback
  }

  if (typeof errorData !== 'object') {
    return String(errorData) || fallback
  }

  const data = errorData as { detail?: unknown; message?: unknown; error?: unknown }
  const rawMessage = data.detail ?? data.message ?? data.error

  if (Array.isArray(rawMessage)) {
    const message = rawMessage.map(formatDetailItem).filter(Boolean).join('; ')
    return message || fallback
  }

  if (rawMessage && typeof rawMessage === 'object') {
    const message = formatDetailItem(rawMessage)
    return message || fallback
  }

  if (rawMessage !== null && rawMessage !== undefined && rawMessage !== '') {
    return String(rawMessage)
  }

  return fallback
}
