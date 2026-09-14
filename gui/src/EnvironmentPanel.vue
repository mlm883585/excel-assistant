<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ppx } from 'ppx-js'

const props = defineProps<{ modelValue: boolean; busy: boolean }>()
const emit = defineEmits(['update:modelValue', 'updated'])
type Check = { name: string; status: string; message: string; impact?: string; action?: string }
type Candidate = { id: string; source: string; cli: string; node_executable: string; version: string; node_version: string; compatible: boolean; reason: string }
const checks = ref<Check[]>([]), candidates = ref<Candidate[]>([]), message = ref('')
const pending = ref(false), runId = ref(''), kind = ref(''), selectedId = ref('')
const messageType = ref<'success' | 'warning' | 'error' | 'info'>('info')
const states: Record<string, string> = { pass: '通过', warn: '需留意', fail: '未通过', cancelled: '已取消', untested: '未检测' }
const call = <T=any>(method: string, params: unknown = {}) => ppx.call<T>(method, params, { timeoutMs: 60000 })

async function perform(fn: () => Promise<void>) {
  if (pending.value) return
  pending.value = true
  try { await fn() } catch (e) { messageType.value='error'; message.value = String(e); ElMessage.error(message.value) }
  finally { pending.value = false; runId.value = ''; kind.value = ''; emit('updated') }
}
async function waitFor(start: { run_id: string }, type: string) {
  runId.value = start.run_id; kind.value = type; message.value = type === 'install' ? '安装进行中，请查看微软安装窗口。' : '正在检测，可取消；关闭此面板不会中断检测。'
  for (;;) {
    const run = await call('diagnostics.get', { run_id: runId.value })
    if (run.state === 'finished') {
      const result = run.result
      message.value = result.message || '本地环境检测完成'
      messageType.value = result.status === 'pass' ? 'success' : result.status === 'fail' ? 'error' : 'warning'
      if (result.checks) checks.value = result.checks
      if (result.candidates) candidates.value = result.candidates
      if (result.selected) selectedId.value = result.selected.id
      if (result.attempts?.length) message.value += '；' + result.attempts.map((a: any) => a.message).join('；')
      return result
    }
    await new Promise(resolve => setTimeout(resolve, 500))
  }
}
async function check(type: string) { await waitFor(await call('diagnostics.check', { kind: type }), type) }
async function refresh() {
  await check('local')
  candidates.value = await call('runtime.discover')
  const status = await call('runtime.status')
  selectedId.value = status.selected?.id || ''
  if (status.first_use && !props.busy) await waitFor(await call('runtime.automatic'), 'automatic')
}
async function useCandidate(candidate: Candidate) {
  const result = await waitFor(await call('runtime.validate', { candidate_id: candidate.id }), 'agent')
  if (result.status === 'pass') {
    await call('runtime.select', { candidate_id: candidate.id })
    selectedId.value = candidate.id; message.value = '已保存已验证的运行环境；后续任务使用此组合。'
  }
}
async function install() {
  await ElMessageBox.confirm('将启动随包 WebView2 离线安装程序，可能出现管理员权限提示。不会在线下载依赖。', '安装 WebView2', { confirmButtonText: '验证并安装', cancelButtonText: '取消' })
  await waitFor(await call('diagnostics.install_webview'), 'install')
}
watch(() => props.modelValue, value => { if (value) void perform(refresh) })
</script>

<template>
  <el-dialog :model-value="modelValue" title="环境检测与运行环境" width="min(1000px, 94vw)" @update:model-value="emit('update:modelValue', $event)">
    <p>优先复用已验证的 Qwen Code。模型或 Excel 不可用时，仍可使用不依赖它们的常用操作。</p>
    <div class="environment-actions">
      <el-button :disabled="pending" @click="perform(refresh)">重新检测本机环境</el-button>
      <el-button :disabled="pending" @click="perform(() => check('model'))">测试已保存的模型连接</el-button>
      <el-button :disabled="pending || busy" @click="perform(() => check('excel'))">测试 Excel 启动</el-button>
      <el-button :disabled="pending" @click="perform(async () => { await call('diagnostics.export'); message='报告已导出或已取消保存' })">导出脱敏报告</el-button>
      <el-button v-if="pending && runId && kind!=='install'" type="warning" @click="call('diagnostics.cancel', {run_id:runId}).catch(e=>ElMessage.error(String(e)))">取消检测</el-button>
    </div>
    <el-alert v-if="message" :title="message" :type="pending ? 'info' : messageType" :closable="false" show-icon />
    <el-table :data="checks" max-height="270" stripe>
      <el-table-column prop="name" label="检查项" width="145" />
      <el-table-column label="状态" width="90"><template #default="{row}"><el-tag :type="row.status==='pass'?'success':row.status==='fail'?'danger':'warning'">{{states[row.status] || row.status}}</el-tag></template></el-table-column>
      <el-table-column prop="message" label="检测结果" min-width="200" />
      <el-table-column label="影响与处理" min-width="200"><template #default="{row}">{{row.impact}}<div v-if="row.status!=='pass'" class="muted">{{row.action}}</div></template></el-table-column>
    </el-table>
    <div class="section-title"><h3>Qwen Code 运行环境</h3><el-button :disabled="pending || busy" @click="perform(async()=>{ candidates=await call('runtime.choose') })">手动选择安装目录</el-button></div>
    <p class="muted">首次兼容列表：CLI 0.23.3。其他版本不会被修改或升级；可选择下方内置组合。路径仅在本机展示，导出时脱敏。</p>
    <el-empty v-if="!candidates.length" description="未发现可用安装；请提供完整交付包或选择安装目录" :image-size="50" />
    <div v-for="candidate in candidates" :key="candidate.id" class="runtime-candidate">
      <strong>{{candidate.source}} · CLI {{candidate.version}} · Node {{candidate.node_version}}</strong>
      <el-tag v-if="selectedId===candidate.id" type="success">当前选择</el-tag>
      <div class="runtime-path">CLI：{{candidate.cli}}<br>Node：{{candidate.node_executable || '未找到'}}</div>
      <div class="section-title"><span>{{candidate.compatible ? '需通过真实协议验证后使用' : candidate.reason}}</span><el-button :disabled="pending || busy || !candidate.compatible" @click="perform(()=>useCandidate(candidate))">{{candidate.source==='随包版本' ? '验证并使用内置版本' : '验证并复用'}}</el-button></div>
    </div>
    <p class="muted">完整 Agent 检测最多 90 秒，只使用本地合成数据；不代表客户模型业务能力已验收。</p>
    <el-button :disabled="pending || busy" @click="perform(install)">安装随包 WebView2</el-button>
  </el-dialog>
</template>

<style scoped>
.environment-actions { display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; }
.environment-actions .el-button { margin-left:0; }
.runtime-candidate { border:1px solid #dce4ec; border-radius:8px; padding:12px; margin:10px 0; }
.runtime-path { overflow-wrap:anywhere; color:#64748b; font-size:12px; margin:8px 0; }
</style>
