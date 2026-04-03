import type { LocationQuery, LocationQueryRaw } from 'vue-router'

export type WorkflowContextSnapshot = {
  company: string
  period: string
  reportTitle: string
}

const STORAGE_KEY = 'ops-pilot-workflow-context'
const EMPTY_CONTEXT: WorkflowContextSnapshot = {
  company: '',
  period: '',
  reportTitle: '',
}

let cachedContext = loadStoredContext()

function normalizeValue(value: unknown): string {
  if (Array.isArray(value)) {
    return normalizeValue(value[0])
  }
  return typeof value === 'string' ? value.trim() : ''
}

function loadStoredContext(): WorkflowContextSnapshot {
  if (typeof window === 'undefined') {
    return { ...EMPTY_CONTEXT }
  }
  const raw = window.sessionStorage.getItem(STORAGE_KEY)
  if (!raw) {
    return { ...EMPTY_CONTEXT }
  }
  try {
    const parsed = JSON.parse(raw) as Partial<WorkflowContextSnapshot>
    return {
      company: normalizeValue(parsed.company),
      period: normalizeValue(parsed.period),
      reportTitle: normalizeValue(parsed.reportTitle),
    }
  } catch {
    window.sessionStorage.removeItem(STORAGE_KEY)
    return { ...EMPTY_CONTEXT }
  }
}

function writeStoredContext(snapshot: WorkflowContextSnapshot) {
  cachedContext = snapshot
  if (typeof window === 'undefined') {
    return
  }
  if (!snapshot.company && !snapshot.period && !snapshot.reportTitle) {
    window.sessionStorage.removeItem(STORAGE_KEY)
    return
  }
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot))
}

function queryValue(query: LocationQuery | LocationQueryRaw | null | undefined, key: string): string {
  if (!query) {
    return ''
  }
  return normalizeValue(query[key])
}

export function getWorkflowContext(): WorkflowContextSnapshot {
  return { ...cachedContext }
}

export function resolveWorkflowContext(
  query?: LocationQuery | LocationQueryRaw | null,
): WorkflowContextSnapshot {
  const stored = getWorkflowContext()
  return {
    company: queryValue(query, 'company') || stored.company,
    period: queryValue(query, 'period') || stored.period,
    reportTitle: queryValue(query, 'report_title') || stored.reportTitle,
  }
}

export function persistWorkflowContext(snapshot: Partial<WorkflowContextSnapshot>) {
  const next: WorkflowContextSnapshot = {
    company: normalizeValue(snapshot.company ?? cachedContext.company),
    period: normalizeValue(snapshot.period ?? cachedContext.period),
    reportTitle: normalizeValue(snapshot.reportTitle ?? cachedContext.reportTitle),
  }
  if (
    next.company === cachedContext.company
    && next.period === cachedContext.period
    && next.reportTitle === cachedContext.reportTitle
  ) {
    return
  }
  writeStoredContext(next)
}

export function clearWorkflowContext() {
  writeStoredContext({ ...EMPTY_CONTEXT })
}

export function buildWorkflowQuery(
  path: string,
  currentQuery: LocationQuery,
  options?: { role?: string },
): LocationQueryRaw | undefined {
  const context = resolveWorkflowContext(currentQuery)
  const query: LocationQueryRaw = {}
  if (['/workspace', '/graph', '/stress', '/score', '/verify', '/vision'].includes(path)) {
    if (context.company) {
      query.company = context.company
    }
    if (context.period) {
      query.period = context.period
    }
  }
  if (path === '/verify' && context.reportTitle) {
    query.report_title = context.reportTitle
  }
  if (path === '/workspace' && options?.role) {
    query.role = options.role
  }
  return Object.keys(query).length ? query : undefined
}
