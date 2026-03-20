<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import StatCard from '@/components/StatCard.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const route = useRoute()
const state = useAsyncState<any>()

const contextText = computed(() => String(route.query.context || route.params.chunkId))
const anchorTerms = computed(() => {
  const raw = typeof route.query.anchors === 'string' ? route.query.anchors : ''
  return raw ? raw.split('|').filter(Boolean) : []
})
const highlightedExcerpt = computed(() => {
  const excerpt = String(state.data.value?.excerpt || '')
  if (!excerpt || anchorTerms.value.length === 0) {
    return escapeHtml(excerpt)
  }
  return anchorTerms.value.reduce((content, term) => {
    if (!term) return content
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return content.replace(new RegExp(escaped, 'gi'), (matched: string) => `<mark>${matched}</mark>`)
  }, escapeHtml(excerpt))
})

function escapeHtml(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

onMounted(() => {
  const chunkId = route.params.chunkId as string
  void state.execute(() => get(`/evidence/${encodeURIComponent(chunkId)}`))
})
</script>

<template>
  <AppShell title="证据查看器" :subtitle="contextText">
    <LoadingState v-if="state.loading.value" />
    <ErrorState v-else-if="state.error.value" :message="state.error.value" />
    <template v-else-if="state.data.value">
      <section class="metrics-grid">
        <StatCard label="来源" :value="state.data.value.source_title" :hint="state.data.value.source_type" />
        <StatCard label="页码" :value="`p.${state.data.value.page}`" :hint="state.data.value.report_period" />
        <StatCard label="公司" :value="state.data.value.company_name" :hint="state.data.value.chunk_id" />
      </section>
      <section>
        <div class="page-header" style="margin-top: 32px; margin-bottom: 16px;"><h3>重点片段</h3></div>
        <div v-if="anchorTerms.length" class="tag-row" style="margin-bottom: 12px;">
          <span class="signal-code">锚点词</span>
          <span v-for="term in anchorTerms" :key="term" class="inline-link">{{ term }}</span>
        </div>
        <div style="padding: 24px; border-radius: 12px; background: #ffffff; border: 1px solid var(--border);">
          <p class="evidence-fulltext evidence-highlight" v-html="highlightedExcerpt" style="margin: 0;" />
        </div>
      </section>
      <section>
        <div class="page-header" style="margin-top: 32px; margin-bottom: 16px;"><h3>来源信息</h3></div>
        <div class="detail-list" style="padding: 24px; border-radius: 12px; border: 1px solid var(--border); background: var(--surface);">
          <div class="detail-row"><span>源链接</span><a class="inline-link" :href="state.data.value.source_url" target="_blank" rel="noreferrer">打开原文</a></div>
          <div class="detail-row"><span>本地路径</span><strong>{{ state.data.value.local_path }}</strong></div>
          <div class="detail-row"><span>指纹</span><strong>{{ state.data.value.fingerprint }}</strong></div>
        </div>
      </section>
    </template>
  </AppShell>
</template>
