<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import FilePreview from './FilePreview.vue'
import ChartPreview from './ChartPreview.vue'
import { call, type Task } from './rpc'
import { ElMessage } from 'element-plus'
import type { OutputReview, OutputChange, ExportResult } from './workbook/types'
import type { WorkbookRecord } from './workbook/adapter'
const props = defineProps<{ task: Task; busy: boolean }>()
const emit = defineEmits<{ openWorkbook: [id: string, exportNow?: boolean, outputId?: string] }>()
const selected = ref('')
const review = ref<OutputReview>(), changes = ref<OutputChange[]>([])
const page = ref(1), reviewLoading = ref(false), reviewError = ref(''), applying = ref(false)
let generation = 0, disposed = false
async function loadReview() {
  const request = ++generation, taskId = props.task.id, outputId = selected.value
  reviewLoading.value = true
  reviewError.value = ''
  try {
    const [summary, result] = await Promise.all([
      call<OutputReview>('outputs.review', { task_id: taskId, output_id: outputId }),
      call<{ items: OutputChange[] }>('outputs.changes', { task_id: taskId, output_id: outputId, offset: (page.value - 1) * 50 }),
    ])
    if (disposed || request !== generation) return
    review.value = summary
    changes.value = result.items
  } catch (error) {
    if (!disposed && request === generation) reviewError.value = String(error)
  } finally {
    if (!disposed && request === generation) reviewLoading.value = false
  }
}
watch(selected, () => {
  ++generation
  page.value = 1
  review.value = undefined
  changes.value = []
  if (selected.value) void loadReview()
})
onBeforeUnmount(() => { disposed = true; ++generation })
async function adopt(exportNow = false) {
  if (applying.value || !review.value) return
  const taskId = props.task.id, outputId = selected.value, summary = review.value
  const current = () => !disposed && props.task.id === taskId && selected.value === outputId
  applying.value = true
  try {
    if (summary.applied_book) {
      if (exportNow) {
        const record = await call<WorkbookRecord>('workbooks.open', { task_id: taskId, workbook_id: summary.applied_book })
        if (!current()) return
        if (record.revision !== summary.applied_revision) {
          throw new Error('工作簿已继续编辑，请打开当前版本重新核对并导出')
        }
      }
      if (current()) emit('openWorkbook', summary.applied_book, exportNow, outputId)
      return
    }
    const result = await call<WorkbookRecord>('outputs.apply', { task_id: taskId, output_id: outputId })
    if (current()) emit('openWorkbook', result.snapshot.id, exportNow, outputId)
  } catch (error) { if (current()) ElMessage.error(String(error)) }
  finally { applying.value = false }
}
async function exportLarge() {
  if (applying.value) return
  applying.value = true
  const outputId = selected.value, taskId = props.task.id
  try {
    const result = await call<ExportResult>('outputs.export', { task_id: taskId, output_id: outputId })
    if (!disposed && selected.value === outputId && result.exported) {
      ElMessage.success('已另存核对结果')
      await loadReview()
    }
  } catch (error) { if (!disposed) ElMessage.error(String(error)) }
  finally { applying.value = false }
}
const operationNames:Record<string,string>={calculate:'新增计算列',classify:'条件分级',create_table:'新建表格',edit_workbook:'区域编辑',clean:'数据清洗',group:'分组汇总',pivot:'矩阵转换',pivot_table:'透视表',melt:'宽表转长表',join:'字段关联',append:'文件合并',compare:'对账'}
watch(() => props.task.outputs.map(f => f.id).join(','), () => { selected.value = props.task.outputs.at(-1)?.id || '' }, { immediate: true })
const file = computed(() => props.task.outputs.find(f => f.id === selected.value))
const labels: Record<string, string> = { input_rows: '各输入表行数', output_rows: '输出行数', issues: '问题总数', written_rows: '写入行数', recalculated: '已执行 Excel 重算' }
function value(v: unknown): string { return Array.isArray(v) ? v.map(value).join(' / ') : v && typeof v === 'object' ? Object.entries(v).map(([k,x]) => `${k}：${value(x)}`).join('；') : typeof v === 'boolean' ? (v ? '是' : '否') : String(v ?? '未提供') }
const detailLabels:Record<string,string>={value:'值',formula:'公式',format:'格式',type:'类型',structure:'结构',result:'结果行',name:'工作表名称',row_count:'行数',column_count:'列数',rows:'行属性',columns:'列属性',merges:'合并区域',freeze:'冻结',filter:'筛选',hidden:'隐藏',height:'高度',width:'宽度',style:'格式',font_name:'字体',font_size:'字号',bold:'粗体',italic:'斜体',underline:'下划线',strike:'删除线',font_color:'文字颜色',bg_color:'背景色',align:'水平对齐',valign:'垂直对齐',text_wrap:'自动换行',rotation:'旋转角度',num_format:'数字格式',borders:'边框',left:'左侧',right:'右侧',top:'顶部',bottom:'底部',color:'颜色',range:'区域',row:'行',column:'列',r0:'起始行',r1:'结束行',c0:'起始列',c1:'结束列',values:'筛选值',blank:'包含空白',hidden_rows:'筛除行'}
const detailValues:Record<string,string>={string:'文本',number:'数字',boolean:'逻辑值',date:'日期',error:'错误',left:'左对齐',right:'右对齐',center:'居中',top:'顶部',bottom:'底部',general:'常规',justify:'两端对齐',thin:'细线',hair:'极细线',medium:'中线',thick:'粗线',double:'双线',dashed:'虚线',dotted:'点线'}
function changeValue(v:unknown,row:OutputChange):string {
  if(row.kind==='type')return v==null?'空':detailValues[String(v)]||String(v)
  if(!['format','structure'].includes(row.kind))return v==null?'空':value(v)
  const format=(item:any,key=''):string=>Array.isArray(item)?item.map(x=>format(x,key)).join(' / '):item && typeof item==='object'?Object.entries(item).map(([k,x])=>`${detailLabels[k]||(['rows','columns'].includes(key)?`第 ${Number(k)+1} ${key==='rows'?'行':'列'}`:k)}：${format(x,k)}`).join('；'):item==null?'无':typeof item==='boolean'?(item?'是':'否'):typeof item==='number'?String(item+(['r0','r1','c0','c1','hidden_rows'].includes(key)?1:0)):detailValues[item]||String(item)
  return format(v,row.property)
}
const metrics = computed(() => Object.entries(file.value?.statistics || {}).filter(([k]) => k in labels))
const extra = computed(() => Object.entries(file.value?.statistics || {}).filter(([k]) => !(k in labels) && k !== 'timings_ms'))
const issueColumns = computed(() => [...new Set((file.value?.issues || []).flatMap(i => Object.keys(i)))])
</script>
<template>
  <section class="panel result-panel">
    <div class="section-title"><div><h2>结果与核对</h2><p class="muted">执行完成后，请结合业务规则核对结果。源文件保持不变。</p></div><slot /></div>
    <el-alert v-if="task.error" :title="task.error" type="error" :closable="false" />
    <div v-if="!task.outputs.length" class="empty">结果生成后，将显示行数、问题明细与来源工作表。</div>
    <template v-if="file">
      <div class="section-title"><el-select v-model="selected" aria-label="结果文件"><el-option v-for="(f,i) in task.outputs" :key="f.id" :value="f.id" :label="`${i+1}. ${f.name}`" /></el-select><el-button v-if="file.kind!=='workbook_candidate'" @click="call('files.open',{task_id:task.id,file_id:file.id}).catch(e=>ElMessage.error(String(e)))">用 Excel 打开</el-button></div>
      <el-alert v-if="reviewError" :title="reviewError" type="error" :closable="false"/>
      <el-alert v-if="review?.legacy" :title="review.message" type="info" :closable="false"/>
      <template v-else-if="review">
        <div class="operation-step"><span>{{review.inputs?.length ? `${review.inputs.length} 个输入` : '无文件建表'}}</span><b>→ {{operationNames[review.operation || ''] || review.operation}} →</b><span>{{file.name}}</span><el-tag v-if="review.base">基于版本 {{review.base.revision}}</el-tag></div>
        <p class="muted">完整核对记录 {{review.total?.toLocaleString()}} 条，每页 50 条。整份采用后可继续编辑，也可以从历史版本恢复。</p>
        <div class="review-counts"><span v-for="(n,k) in review.counts" :key="k">{{({value:'值变化',formula:'公式变化',format:'格式变化',type:'类型变化',structure:'结构变化',result:'完整结果行'} as any)[k] || k}} {{n}}</span></div>
        <el-table :data="changes" v-loading="reviewLoading" max-height="420" row-key="id" class="change-table"><el-table-column prop="location" label="位置 / 来源" min-width="180"/><el-table-column label="修改内容" width="110"><template #default="{row}">{{detailLabels[row.property || row.kind] || row.kind}}</template></el-table-column><el-table-column label="原值 / 原结构" min-width="220"><template #default="{row}"><span class="old-value">{{changeValue(row.old,row)}}</span></template></el-table-column><el-table-column label="新值 / 新结构" min-width="220"><template #default="{row}"><span class="new-value">{{changeValue(row.new,row)}}</span><p v-if="row.note" class="muted">{{row.note}}</p></template></el-table-column></el-table>
        <div class="section-title"><el-pagination v-model:current-page="page" :page-size="50" :total="review.total" layout="prev,pager,next,jumper" @current-change="loadReview"/><div v-if="review.can_edit"><el-button :disabled="busy || reviewLoading || applying" @click="adopt()">{{review.applied_book?'打开并继续编辑':'采用并继续编辑'}}</el-button><el-button type="primary" :disabled="busy || reviewLoading || applying" @click="adopt(true)">确认并导出</el-button></div><el-button v-else type="primary" :disabled="busy || reviewLoading || applying" @click="exportLarge">确认并导出</el-button></div>
        <p v-if="!review.can_edit" class="muted">{{review.limitations?.length ? review.limitations.join('；') : '此结果超出完整编辑容量，已保留全量数据，可核对所有分页并导出。'}}</p>
        <el-alert v-if="review.requires_excel_recalculation" title="请先用 Excel 原生重算此副本，再核对并导出。" type="warning" :closable="false"/>
      </template>
      <div class="metrics"><div v-for="[key,v] in metrics" :key="key"><span>{{labels[key]}}</span><strong>{{value(v)}}</strong></div></div>
      <details v-if="extra.length"><summary>其他统计</summary><p v-for="[key,v] in extra" :key="key">{{key}}：{{value(v)}}</p></details>
      <details v-if="file.issues?.length" class="issues" open><summary>检查事项 · 当前展示 {{file.issues.length}} 条<span v-if="file.statistics?.issues!==undefined"> / 共 {{file.statistics.issues}} 条</span></summary><p class="muted">完整问题记录请查看输出工作簿的“问题明细”；模板提示不代表公式实机验收已完成。</p><el-table :data="file.issues" max-height="220"><el-table-column v-for="key in issueColumns" :key="key" :label="key" min-width="150"><template #default="{row}">{{value(row[key])}}</template></el-table-column></el-table></details>
      <ChartPreview v-if="file.chart" :chart="file.chart" />
      <FilePreview v-if="file.kind!=='workbook_candidate'" :task-id="task.id" :file="file" :busy="busy" />
    </template>
  </section>
</template>
<style scoped>.operation-step{display:flex;gap:14px;align-items:center;padding:16px;background:#f3f6fa;border-radius:8px;margin-top:16px}.review-counts{display:flex;gap:16px;margin:12px 0;font-size:12px;color:#53657c}.old-value{white-space:pre-wrap;background:#fff0ee;color:#9b4238}.new-value{white-space:pre-wrap;background:#e9f7ef;color:#246d48}.change-table{margin-bottom:16px}</style>
