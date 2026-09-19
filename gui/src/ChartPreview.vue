<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ChartData } from './rpc'

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TitleComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ chart: ChartData }>()
const host = ref<HTMLElement>()
let instance: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

function option(): echarts.EChartsCoreOption {
  const { type, title, labels, series } = props.chart
  const names = series.map(s => s.name)
  const base = {
    title: title ? { text: title, left: 'center' } : undefined,
    tooltip: { trigger: type === 'pie' ? 'item' : 'axis' },
    legend: names.length > 1 ? { bottom: 0 } : undefined,
    grid: { left: 16, right: 16, top: 40, bottom: names.length > 1 ? 40 : 12, containLabel: true },
  }
  if (type === 'pie') {
    return {
      ...base,
      series: [{
        type: 'pie',
        radius: ['28%', '62%'],
        center: ['50%', '50%'],
        data: labels.map((name, i) => ({ name: String(name), value: series[0]?.values[i] ?? 0 })),
        label: { formatter: '{b}: {c}' },
      }],
    }
  }
  const horizontal = type === 'bar'
  const categoryAxis = { type: 'category', data: labels.map(String) }
  const valueAxis = { type: 'value' }
  return {
    ...base,
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? categoryAxis : valueAxis,
    series: series.map((s, i) => ({
      name: s.name,
      type: type === 'column' || type === 'bar' ? 'bar' : 'line',
      data: s.values,
      smooth: type !== 'column' && type !== 'bar',
      areaStyle: type === 'area' ? {} : undefined,
      itemStyle: type === 'area' ? { opacity: 0.7 } : undefined,
      barMaxWidth: 42,
    })),
  }
}

function render() {
  if (!instance || !host.value) return
  instance.setOption(option(), true)
}

onMounted(() => {
  if (!host.value) return
  instance = echarts.init(host.value)
  render()
  resizeObserver = new ResizeObserver(() => instance?.resize())
  resizeObserver.observe(host.value)
})
watch(() => props.chart, render, { deep: true })
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  instance?.dispose()
  instance = null
})
</script>

<template>
  <div class="chart-preview">
    <div v-if="!chart.labels?.length" class="chart-empty">暂无图表数据</div>
    <div ref="host" class="chart-host" :aria-label="chart.title || '图表预览'" />
  </div>
</template>

<style scoped>
.chart-preview { margin: 16px 0; border: 1px solid #e4e8ee; border-radius: 8px; background: #fff; overflow: hidden; }
.chart-host { width: 100%; height: 360px; }
.chart-empty { display: flex; align-items: center; justify-content: center; height: 160px; color: #8a97a8; }
</style>
