<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingState from '@/components/LoadingState.vue'
import TagPill from '@/components/TagPill.vue'
import { useAsyncState } from '@/composables/useAsyncState'
import { get } from '@/lib/api'

const overviewState = useAsyncState<any>()
const upgradesState = useAsyncState<any>()
const detailState = useAsyncState<any>()

const companies = computed(() => overviewState.data.value?.companies || [])
const selectedCompany = ref('')
const selectedUpgradeKey = ref('')

const upgradeItems = computed(() => upgradesState.data.value?.items || [])
const selectedUpgrade = computed(() =>
  upgradeItems.value.find((item: any) => `${item.stage}::${item.report_id}` === selectedUpgradeKey.value) || null,
)

async function loadUpgrades() {
  if (!selectedCompany.value) return
  await upgradesState.execute(() =>
    get(`/company/document-upgrades?company_name=${encodeURIComponent(selectedCompany.value)}&limit=20`),
  )
}

async function loadDetail() {
  if (!selectedUpgrade.value) return
  await detailState.execute(() =>
    get(
      `/admin/document-pipeline/results/${encodeURIComponent(selectedUpgrade.value.stage)}/${encodeURIComponent(
        selectedUpgrade.value.report_id,
      )}`,
    ),
  )
}

onMounted(async () => {
  await overviewState.execute(() => get('/workspace/overview?user_role=management'))
  selectedCompany.value = companies.value[0] || ''
  await loadUpgrades()
  if (upgradeItems.value.length) {
    selectedUpgradeKey.value = `${upgradeItems.value[0].stage}::${upgradeItems.value[0].report_id}`
  }
})

watch(selectedCompany, async () => {
  selectedUpgradeKey.value = ''
  await loadUpgrades()
  if (upgradeItems.value.length) {
    selectedUpgradeKey.value = `${upgradeItems.value[0].stage}::${upgradeItems.value[0].report_id}`
  }
})

watch(selectedUpgradeKey, async () => {
  await loadDetail()
})
</script>

<template>
  <AppShell title="多模态图表解析" subtitle="Vision Analyzer" compact>
    <LoadingState v-if="overviewState.loading.value && !upgradesState.data.value" />
    <ErrorState
      v-else-if="overviewState.error.value || upgradesState.error.value || detailState.error.value"
      :message="String(overviewState.error.value || upgradesState.error.value || detailState.error.value)"
    />
    <template v-else>
      <section class="mode-header">
        <div class="mode-header-copy">
          <div class="eyebrow">Document upgrade consumption</div>
          <h2 class="hero-title compact">从已解析文档里取结构、跨页结果和证据入口，不再看原始 JSON。</h2>
        </div>
      </section>

      <section class="mode-stage vision-mode-stage">
        <article class="panel mode-main-panel vision-main-panel">
          <div class="vision-layout">
            <div class="vision-input-zone">
              <label class="field">
                <span>公司</span>
                <select v-model="selectedCompany">
                  <option v-for="company in companies" :key="company" :value="company">{{ company }}</option>
                </select>
              </label>
              <div class="vision-dropzone">
                <div class="vision-drop-icon">⇪</div>
                <strong>选择已解析报告</strong>
                <span>当前先消费真实文档升级结果，后续再接 OCR 运行时。</span>
              </div>
              <div class="timeline-list compact-timeline">
                <button
                  v-for="item in upgradeItems"
                  :key="`${item.stage}::${item.report_id}`"
                  type="button"
                  class="timeline-item interactive-card"
                  :class="{ 'is-active-card': selectedUpgradeKey === `${item.stage}::${item.report_id}` }"
                  @click="selectedUpgradeKey = `${item.stage}::${item.report_id}`"
                >
                  <strong>{{ item.stage }}</strong>
                  <span>{{ item.report_period || '-' }} · {{ item.artifact_summary || item.report_id }}</span>
                </button>
              </div>
            </div>

            <div class="vision-result-zone">
              <div class="panel-header">
                <div>
                  <div class="eyebrow">Analysis Result</div>
                  <h3>{{ selectedUpgrade?.company_name || '等待选择报告' }}</h3>
                </div>
                <TagPill v-if="selectedUpgrade" :label="selectedUpgrade.stage" />
              </div>
              <div v-if="detailState.data.value" class="vision-sections">
                <article
                  v-for="section in detailState.data.value.consumable_sections || []"
                  :key="section.section_type"
                  class="vision-section-card"
                >
                  <div class="signal-code">{{ section.title }}</div>
                  <strong>{{ section.count }} 条</strong>
                  <div class="metric-list">
                    <div v-for="item in section.items.slice(0, 5)" :key="JSON.stringify(item)" class="metric-row">
                      <span>{{ item.text || item.title || item.reason || '条目' }}</span>
                      <strong>{{ item.page || item.level || item.to_page || '-' }}</strong>
                    </div>
                  </div>
                </article>
              </div>
              <div v-else class="vision-empty">
                <span>Waiting for analysis result</span>
              </div>
            </div>
          </div>
        </article>

        <aside class="mode-side-panel">
          <section class="panel side-panel-block">
            <div class="panel-header">
              <div>
                <div class="eyebrow">解析跳转</div>
                <h3>证据与详情</h3>
              </div>
            </div>
            <div class="timeline-list compact-timeline">
              <RouterLink
                v-for="item in detailState.data.value?.evidence_navigation?.links || []"
                :key="item.label + item.path"
                class="timeline-item interactive-card"
                :to="{ path: item.path, query: item.query || {} }"
              >
                <strong>{{ item.label }}</strong>
              </RouterLink>
            </div>
          </section>
        </aside>
      </section>
    </template>
  </AppShell>
</template>
