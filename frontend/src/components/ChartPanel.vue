<script setup lang="ts">
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, RadarChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { init, use } from 'echarts/core'
import type { ECharts } from 'echarts/core'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{
  title: string
  options: Record<string, unknown>
}>()

const root = ref<HTMLElement | null>(null)
let instance: ECharts | null = null

use([
  CanvasRenderer,
  BarChart,
  LineChart,
  RadarChart,
  GridComponent,
  LegendComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
])

function renderChart() {
  if (!root.value) return
  if (!instance) {
    instance = init(root.value)
  }
  instance.setOption(props.options, true)
}

function resizeChart() {
  instance?.resize()
}

onMounted(() => {
  renderChart()
  window.addEventListener('resize', resizeChart)
})

watch(() => props.options, renderChart, { deep: true })

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  instance?.dispose()
  instance = null
})
</script>

<template>
  <section class="panel chart-panel">
    <div class="panel-header">
      <h3>{{ title }}</h3>
    </div>
    <div ref="root" class="chart-root"></div>
  </section>
</template>
