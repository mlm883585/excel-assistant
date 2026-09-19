<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { call, type PivotPreview, type Selection } from './rpc'

const props = defineProps<{ taskId: string; selection: Selection; fields: string[]; busy: boolean; singleValue: boolean }>()
const rows = ref<string[]>([])
const column = ref('')
const values = ref<string[]>([])
const aggregate = ref('sum')
const preview = ref<PivotPreview>()
const previewError = ref('')
let timer: number | undefined
let generation = 0

const aggregateOptions = [
  { value: 'sum', label: '求和' },
  { value: 'count', label: '计数' },
  { value: 'min', label: '最小值' },
  { value: 'max', label: '最大值' },
  { value: 'mean', label: '平均值' },
]

function schedule() {
  window.clearTimeout(timer)
  timer = window.setTimeout(refresh, 300)
}

async function refresh() {
  const request = ++generation
  const selection = props.selection
  if (!selection.file_id || !rows.value.length || !values.value.length) {
    preview.value = undefined
    previewError.value = ''
    return
  }
  try {
    const result = await call<PivotPreview>('pivot.preview', {
      task_id: props.taskId,
      selection,
      rows: rows.value,
      columns: column.value ? [column.value] : [],
      values: values.value,
      aggregate: aggregate.value,
    })
    if (request === generation) { preview.value = result; previewError.value = '' }
  } catch (error) {
    if (request === generation) { preview.value = undefined; previewError.value = String(error) }
  }
}

watch([rows, column, values, aggregate], schedule)
watch(() => props.selection, schedule)
onBeforeUnmount(() => { window.clearTimeout(timer); ++generation })

function spec() {
  return { rows: rows.value, columns: column.value ? [column.value] : [], values: values.value, aggregate: aggregate.value }
}
defineExpose({ spec })
</script>

<template>
  <div class="pivot-builder">
    <label class="field-label">行字段（可多选）</label>
    <el-select v-model="rows" multiple aria-label="行字段" :disabled="busy" placeholder="选择作为行标签的字段">
      <el-option v-for="c in fields" :key="c" :value="c" :label="c" />
    </el-select>
    <label class="field-label">列字段（选 1 个，可留空）</label>
    <el-select v-model="column" clearable aria-label="列字段" :disabled="busy" placeholder="选择作为列标签的字段">
      <el-option v-for="c in fields" :key="c" :value="c" :label="c" />
    </el-select>
    <label class="field-label">{{ singleValue ? '数值字段（选 1 个）' : '数值字段（可多选）' }}</label>
    <el-select v-model="values" multiple :multiple-limit="singleValue ? 1 : 0" aria-label="数值字段" :disabled="busy" placeholder="选择要汇总的数值字段">
      <el-option v-for="c in fields" :key="c" :value="c" :label="c" />
    </el-select>
    <label class="field-label">汇总方式</label>
    <el-select v-model="aggregate" aria-label="汇总方式" :disabled="busy">
      <el-option v-for="a in aggregateOptions" :key="a.value" :value="a.value" :label="a.label" />
    </el-select>
    <p v-if="previewError" class="muted">{{ previewError }}</p>
    <el-table v-else-if="preview" :data="preview.rows" max-height="320" size="small" class="pivot-preview-table">
      <el-table-column v-for="c in preview.columns" :key="c" :label="c" min-width="120">
        <template #default="{ row }">{{ row[c] }}</template>
      </el-table-column>
    </el-table>
    <p v-else class="muted">选择行、数值字段后自动预览；结果超过 5000 个单元格时会提示缩小范围。</p>
  </div>
</template>

<style scoped>
.pivot-builder { display: flex; flex-direction: column; gap: 8px; }
.pivot-preview-table { margin-top: 4px; }
</style>
