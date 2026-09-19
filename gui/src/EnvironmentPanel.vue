<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElDrawer, ElEmpty } from 'element-plus'
import { ppx } from 'ppx-js'
import { checks, candidates, message, pending, runId, kind, selectedId, initialized, messageType, modelStatus, excelStatus, modelList, type Candidate } from './environmentState'

const props = defineProps<{ modelValue: boolean; busy: boolean }>()
const emit = defineEmits(['update:modelValue', 'updated'])
const tab = ref('overview'), settings = ref({base_url:'', model:'', fallback_base_url:'', fallback_model:'', agent_backend:'native'})
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
      if (type === 'model') modelStatus.value = states[result.status] || result.status
      if (type === 'model' && Array.isArray(result.models)) modelList.value = result.models
      if (type === 'excel') excelStatus.value = states[result.status] || result.status
      if (result.attempts?.length) message.value += '；' + result.attempts.map((a: any) => a.message).join('；')
      return result
    }
    await new Promise(resolve => setTimeout(resolve, 500))
  }
}
async function check(type: string, config?: unknown) { await waitFor(await call('diagnostics.check', { kind: type, ...(config ? { config } : {}) }), type) }
async function refresh() {
  await check('local')
  candidates.value = await call('runtime.discover')
  const status = await call('runtime.status')
  selectedId.value = status.selected?.id || ''
  const got = await call('settings.get')
  settings.value = { base_url: got.base_url || '', model: got.model || '', fallback_base_url: got.fallback?.base_url || '', fallback_model: got.fallback?.model || '', agent_backend: got.agent_backend || 'native' }
  initialized.value = true
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
watch(() => props.modelValue, value => { if (value && !initialized.value) void perform(refresh) }, { immediate: true })
</script>

<template>
  <el-drawer :model-value="modelValue" title="设置与环境" size="min(1050px, 96vw)" @update:model-value="emit('update:modelValue', $event)">
    <p>优先复用已验证的 Qwen Code。模型或 Excel 不可用时，仍可使用不依赖它们的常用操作。</p>
    <el-tabs v-model="tab"><el-tab-pane label="使用状态" name="overview"/><el-tab-pane label="模型连接" name="model"/><el-tab-pane label="高级诊断" name="advanced"/></el-tabs>
    <div v-if="tab==='overview'" class="metrics"><div><span>常用数据操作</span><strong>{{checks.some(c=>c.status==='fail')?'请查看本机检查':'不依赖模型'}}</strong></div><div><span>智能处理后端</span><strong>{{settings.agent_backend==='qwen' ? (selectedId?'已验证':'待配置') : '原生直连'}}</strong></div><div><span>模型连接</span><strong>{{modelStatus}}</strong></div><div><span>Excel 启动测试</span><strong>{{excelStatus}}</strong></div></div>
    <div v-if="tab==='model'" class="model-settings"><label class="field-label">主模型服务地址</label><el-input v-model="settings.base_url" aria-label="主模型服务地址" placeholder="http://内网地址:端口/v1"/><label class="field-label">主模型标识</label><el-select v-model="settings.model" filterable allow-create default-first-option aria-label="主模型标识" placeholder="输入或从列表选择"><el-option v-for="m in modelList" :key="m" :value="m" :label="m"/></el-select><el-button :disabled="pending || busy" @click="perform(() => check('model', {base_url: settings.base_url, model: settings.model}))">检测并列出模型</el-button><label class="field-label">备用服务地址（可选）</label><el-input v-model="settings.fallback_base_url" aria-label="备用服务地址" placeholder="主服务不可用时自动降级"/><label class="field-label">备用模型标识</label><el-select v-model="settings.fallback_model" filterable allow-create default-first-option aria-label="备用模型标识" placeholder="输入或从列表选择"><el-option v-for="m in modelList" :key="m" :value="m" :label="m"/></el-select><label class="field-label">智能处理后端</label><el-radio-group v-model="settings.agent_backend" :disabled="pending || busy"><el-radio-button value="native">原生直连（推荐）</el-radio-button><el-radio-button value="qwen">Qwen Code</el-radio-button></el-radio-group><p class="muted">原生直连只需模型端点，无需安装 Node / Qwen Code CLI；Qwen Code 作为可选后端保留。</p><p class="muted">密钥由 IT 通过 EXCEL_ASSISTANT_API_KEY（备用 EXCEL_ASSISTANT_FALLBACK_API_KEY，缺省沿用主密钥）配置。保存不代表模型可用，请单独检测。</p><el-button class="execute" :disabled="pending || busy" type="primary" @click="perform(async()=>{await call('settings.save',settings);modelStatus='未检测';message='模型设置已保存'})">保存模型设置</el-button></div>
    <div class="environment-actions">
      <el-button :disabled="pending" @click="perform(refresh)">重新检测本机环境</el-button>
      <el-button :disabled="pending" @click="perform(() => check('model'))">测试已保存的模型连接</el-button>
      <el-button :disabled="pending || busy" @click="perform(() => check('excel'))">测试 Excel 启动</el-button>
      <el-button :disabled="pending" @click="perform(async () => { message=await call('diagnostics.export') ? '脱敏报告已导出' : '已取消保存报告' })">导出脱敏报告</el-button>
      <el-button v-if="pending && runId && kind!=='install'" type="warning" @click="call('diagnostics.cancel', {run_id:runId}).catch(e=>ElMessage.error(String(e)))">取消检测</el-button>
    </div>
    <el-alert v-if="message" :title="message" :type="pending ? 'info' : messageType" :closable="false" show-icon />
    <el-table v-if="tab!=='model'" :data="checks" stripe>
      <el-table-column prop="name" label="检查项" width="145" />
      <el-table-column label="状态" width="90"><template #default="{row}"><el-tag :type="row.status==='pass'?'success':row.status==='fail'?'danger':'warning'">{{states[row.status] || row.status}}</el-tag></template></el-table-column>
      <el-table-column prop="message" label="检测结果" min-width="200" />
      <el-table-column label="影响与处理" min-width="200"><template #default="{row}">{{row.impact}}<div v-if="row.status!=='pass'" class="muted">{{row.action}}</div></template></el-table-column>
    </el-table>
    <template v-if="tab==='advanced'"><div class="section-title"><h3>Qwen Code 运行环境</h3><el-button :disabled="pending || busy" @click="perform(async()=>{ candidates=await call('runtime.choose') })">手动选择安装目录</el-button></div>
    <el-button :disabled="pending || busy" @click="perform(async()=>{await waitFor(await call('runtime.automatic'),'automatic')})">自动验证已有安装</el-button>
    <p class="muted">首次兼容列表：CLI 0.23.3。其他版本不会被修改或升级；可选择下方内置组合。路径仅在本机展示，导出时脱敏。</p>
    <el-empty v-if="!candidates.length" description="未发现可用安装；请提供完整交付包或选择安装目录" :image-size="50" />
    <div v-for="candidate in candidates" :key="candidate.id" class="runtime-candidate">
      <strong>{{candidate.source}} · CLI {{candidate.version}} · Node {{candidate.node_version}}</strong>
      <el-tag v-if="selectedId===candidate.id" type="success">当前选择</el-tag>
      <details><summary>查看安装路径</summary><div class="runtime-path">CLI：{{candidate.cli}}<br>Node：{{candidate.node_executable || '未找到'}}</div></details>
      <div class="section-title"><span>{{candidate.compatible ? '需通过真实协议验证后使用' : candidate.reason}}</span><el-button :disabled="pending || busy || !candidate.compatible" @click="perform(()=>useCandidate(candidate))">{{candidate.source==='随包版本' ? '验证并使用内置版本' : '验证并复用'}}</el-button></div>
    </div>
    <p class="muted">完整 Agent 检测最多 90 秒，只使用本地合成数据；不代表客户模型业务能力已验收。</p>
    <el-button :disabled="pending || busy" @click="perform(install)">安装随包 WebView2</el-button>
    </template><el-button v-if="tab==='overview' && !selectedId && settings.agent_backend==='qwen'" type="primary" @click="tab='advanced'">配置智能处理运行环境</el-button>
  </el-drawer>
</template>

<style scoped>
.environment-actions { display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; }
.environment-actions .el-button { margin-left:0; }
.runtime-candidate { border:1px solid #dce4ec; border-radius:8px; padding:12px; margin:10px 0; }
.runtime-path { overflow-wrap:anywhere; color:#64748b; font-size:12px; margin:8px 0; }
</style>
