<script setup lang="ts">
import type { ECharts } from 'echarts/core'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{
  title: string
  options: Record<string, unknown>
}>()

const root = ref<HTMLElement | null>(null)
let instance: ECharts | null = null
let chartRuntimePromise: Promise<{ init: (element: HTMLElement) => ECharts }> | null = null

async function loadChartRuntime() {
  if (!chartRuntimePromise) {
    chartRuntimePromise = (async () => {
      const [{ init, use }, charts, components, renderers] = await Promise.all([
        import('echarts/core'),
        import('echarts/charts'),
        import('echarts/components'),
        import('echarts/renderers'),
      ])
      use([
        renderers.CanvasRenderer,
        charts.BarChart,
        charts.LineChart,
        charts.RadarChart,
        components.GridComponent,
        components.LegendComponent,
        components.RadarComponent,
        components.TitleComponent,
        components.TooltipComponent,
      ])
      return { init }
    })()
  }
  return chartRuntimePromise
}

async function renderChart() {
  await nextTick()
  if (!root.value) return
  const { init } = await loadChartRuntime()
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
  void renderChart()
  window.addEventListener('resize', resizeChart)
})

watch(
  () => props.options,
  () => {
    void renderChart()
  },
  { deep: true },
)

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
