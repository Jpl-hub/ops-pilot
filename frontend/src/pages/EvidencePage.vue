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
      <section class="panel">
        <div class="panel-header"><h3>重点片段</h3></div>
        <p class="evidence-fulltext">{{ state.data.value.excerpt }}</p>
      </section>
      <section class="panel">
        <div class="panel-header"><h3>来源信息</h3></div>
        <div class="detail-list">
          <div class="detail-row"><span>源链接</span><a class="inline-link" :href="state.data.value.source_url" target="_blank" rel="noreferrer">打开原文</a></div>
          <div class="detail-row"><span>本地路径</span><strong>{{ state.data.value.local_path }}</strong></div>
          <div class="detail-row"><span>指纹</span><strong>{{ state.data.value.fingerprint }}</strong></div>
        </div>
      </section>
    </template>
  </AppShell>
</template>
