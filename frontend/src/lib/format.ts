export function buildEvidenceLink(chunkId: string, context?: string, anchors?: string[]): string {
  const params = new URLSearchParams()
  if (context) params.set('context', context)
  if (anchors?.length) params.set('anchors', anchors.join('|'))
  const query = params.toString()
  return `/evidence/${encodeURIComponent(chunkId)}${query ? `?${query}` : ''}`
}
