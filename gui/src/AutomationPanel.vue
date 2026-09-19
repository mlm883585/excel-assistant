<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { ppx } from 'ppx-js'
import { schedules, recipes, active, queueLen, pending, initialized, message, messageType } from './schedulerState'
import { runStatusLabels, type AutomationStatus, type Recipe, type Schedule } from './rpc'

const props = defineProps<{ modelValue: boolean; busy: boolean }>()
const emit = defineEmits(['update:modelValue', 'updated'])
const call = <T = any>(method: string, params: unknown = {}) => ppx.call<T>(method, params, { timeoutMs: 60000 })

const tab = ref('list')
const editingId = ref('')
const form = reactive({ name: '', recipe_id: '', source_dir: '', output_dir: '', trigger_type: 'manual' as 'manual' | 'cron', cron: '0 9 * * *' })
const cronPresets: [string, string][] = [['0 9 * * *', '每天 09:00'], ['0 * * * *', '每小时整点'], ['0 9 * * 1', '每周一 09:00']]
const runStates: Record<string, string> = { running: 'warning', succeeded: 'success', failed: 'danger', partial: 'warning', cancelled: 'info' }

let timer: number | undefined

async function perform(fn: () => Promise<void>) {
  if (pending.value) return
  pending.value = true
  try { await fn() } catch (e) { messageType.value = 'error'; message.value = String(e); ElMessage.error(message.value) }
  finally { pending.value = false; emit('updated') }
}

async function refresh() {
  schedules.value = await call<Schedule[]>('automation.list')
  const all = await call<Recipe[]>('recipes.list')
  recipes.value = all.filter(r => Array.isArray(r.slots) && r.slots.length === 1)
  initialized.value = true
}

async function pollActive() {
  const status = await call<AutomationStatus>('automation.status')
  const wasActive = !!active.value
  active.value = status.active
  queueLen.value = status.queue_len
  if (status.active || status.queue_len > 0) {
    timer = window.setTimeout(pollActive, 800)
  } else if (wasActive) {
    void refresh()
  }
}

function cronLabel(cron: string): string {
  return cronPresets.find(([expr]) => expr === cron)?.[1] || cron
}
function triggerSummary(s: Schedule): string {
  return s.trigger.type === 'cron' ? cronLabel(s.trigger.cron) : '手动触发'
}
function fmt(value: string | null | undefined): string {
  return value ? value.replace('T', ' ') : '—'
}

async function chooseFolder(key: 'source_dir' | 'output_dir') {
  const path = await call<string | null>('automation.choose_folder')
  if (path) form[key] = path
}

function startEdit(schedule: Schedule) {
  editingId.value = schedule.id
  form.name = schedule.name
  form.recipe_id = schedule.recipe_id
  form.source_dir = schedule.source_dir
  form.output_dir = schedule.output_dir
  form.trigger_type = schedule.trigger.type
  form.cron = schedule.trigger.type === 'cron' ? schedule.trigger.cron : '0 9 * * *'
  tab.value = 'form'
}

function newForm() {
  editingId.value = ''
  Object.assign(form, { name: '', recipe_id: '', source_dir: '', output_dir: '', trigger_type: 'manual', cron: '0 9 * * *' })
  tab.value = 'form'
}

async function save() {
  const body: Record<string, unknown> = {
    name: form.name,
    recipe_id: form.recipe_id,
    source_dir: form.source_dir,
    output_dir: form.output_dir,
    trigger: form.trigger_type === 'cron' ? { type: 'cron', cron: form.cron.trim() } : { type: 'manual' },
  }
  const existing = schedules.value.find(s => s.id === editingId.value)
  if (existing) {
    body.id = existing.id
    body.created_at = existing.created_at
    body.last_run_at = existing.last_run_at
    body.runs = existing.runs
    body.enabled = existing.enabled
  }
  const saved = await call<Schedule>('automation.save', body)
  message.value = '自动化任务已保存'
  messageType.value = 'success'
  await refresh()
  if (saved.next_run_at) message.value += `；下次执行 ${fmt(saved.next_run_at)}`
  tab.value = 'list'
}

async function remove(schedule: Schedule) {
  await ElMessageBox.confirm(`删除「${schedule.name}」？已产生的输出文件不会受影响。`, '删除自动化任务', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' })
  await call('automation.delete', { schedule_id: schedule.id })
  message.value = '已删除'
  messageType.value = 'success'
  await refresh()
}

async function runNow(schedule: Schedule) {
  await call('automation.run', { schedule_id: schedule.id })
  message.value = '已加入运行队列'
  messageType.value = 'success'
  void pollActive()
}

async function toggle(row: Schedule, enabled: boolean) {
  try {
    Object.assign(row, await call<Schedule>('automation.toggle', { schedule_id: row.id, enabled }))
    message.value = enabled ? '已启用定时' : '已停用定时'
    messageType.value = 'success'
  } catch (e) {
    ElMessage.error(String(e))
    await refresh()
  }
}

watch(() => props.modelValue, value => { if (value && !initialized.value) void perform(refresh) }, { immediate: true })
onBeforeUnmount(() => { if (timer) window.clearTimeout(timer) })
</script>

<template>
  <el-drawer :model-value="modelValue" title="批量与定时自动化" size="min(1050px, 96vw)" @update:model-value="emit('update:modelValue', $event)">
    <p class="muted">把已保存的单文件常用规则，批量套用到整个文件夹的表格上，并按时间表自动运行。定时仅在应用运行时触发；关闭期间错过的运行会跳过、不补跑。源文件只读，结果写入输出文件夹下按运行时间命名的子目录。</p>
    <el-tabs v-model="tab"><el-tab-pane label="自动化任务" name="list" /><el-tab-pane :label="editingId ? '编辑任务' : '新建任务'" name="form" /><el-tab-pane label="运行历史" name="history" /></el-tabs>

    <el-alert v-if="active" class="run-banner" type="warning" :closable="false" show-icon>
      <template #title>正在批量运行：成功 {{ active.succeeded }} / {{ active.total }}，失败 {{ active.failed }}</template>
      <div class="muted">当前输入：{{ active.items.find(i => i.status === 'running')?.input || '准备中…' }}{{ queueLen > 1 ? ` · 队列中还有 ${queueLen - 1} 项` : '' }}</div>
    </el-alert>
    <el-alert v-if="busy" title="当前有前台任务在处理，批量运行会自动等待其结束。" type="info" :closable="false" show-icon />

    <div v-if="tab === 'list'">
      <div class="panel-actions"><el-button type="primary" :icon="Plus" @click="newForm">新建自动化任务</el-button><el-button :disabled="pending" @click="perform(refresh)">刷新</el-button></div>
      <el-empty v-if="!schedules.length" description="还没有自动化任务；先完成一次处理并保存为常用规则，再在此建立批量或定时。" :image-size="60" />
      <el-table v-else :data="schedules" stripe>
        <el-table-column prop="name" label="名称" min-width="130" />
        <el-table-column label="规则" min-width="120"><template #default="{ row }">{{ row.recipe_name || '—' }}</template></el-table-column>
        <el-table-column label="触发" width="110"><template #default="{ row }">{{ triggerSummary(row) }}</template></el-table-column>
        <el-table-column label="启用" width="70"><template #default="{ row }"><el-switch :model-value="row.enabled" @change="toggle(row, $event)" /></template></el-table-column>
        <el-table-column label="下次执行" width="150"><template #default="{ row }">{{ fmt(row.next_run_at) }}</template></el-table-column>
        <el-table-column label="上次执行" width="150"><template #default="{ row }">{{ fmt(row.last_run_at) }}</template></el-table-column>
        <el-table-column label="操作" width="180"><template #default="{ row }"><el-button size="small" :disabled="!!active" @click="runNow(row)">立即运行</el-button><el-button size="small" @click="startEdit(row)">编辑</el-button><el-button size="small" type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
      </el-table>
    </div>

    <div v-else-if="tab === 'form'" class="schedule-form">
      <label class="field-label">任务名称</label>
      <el-input v-model="form.name" aria-label="任务名称" placeholder="例如：月末结算汇总" />
      <label class="field-label">套用规则（单文件规则）</label>
      <el-select v-model="form.recipe_id" aria-label="套用规则" placeholder="选择一个已保存的规则">
        <el-option v-for="r in recipes" :key="r.id" :value="r.id" :label="r.name" />
      </el-select>
      <p v-if="!recipes.length" class="muted">还没有单文件规则。请先在结果页把一次成功处理「保存为常用任务」。</p>
      <label class="field-label">输入文件夹</label>
      <div class="folder-row"><el-input v-model="form.source_dir" aria-label="输入文件夹" placeholder="遍历此文件夹内的 xlsx / xls / csv" /><el-button @click="chooseFolder('source_dir')">选择文件夹</el-button></div>
      <label class="field-label">输出文件夹</label>
      <div class="folder-row"><el-input v-model="form.output_dir" aria-label="输出文件夹" placeholder="结果写入此文件夹的时间戳子目录" /><el-button @click="chooseFolder('output_dir')">选择文件夹</el-button></div>
      <label class="field-label">触发方式</label>
      <el-radio-group v-model="form.trigger_type">
        <el-radio-button value="manual">手动触发</el-radio-button>
        <el-radio-button value="cron">定时触发</el-radio-button>
      </el-radio-group>
      <template v-if="form.trigger_type === 'cron'">
        <label class="field-label">时间表达式（分 时 日 月 周）</label>
        <el-input v-model="form.cron" aria-label="时间表达式" placeholder="0 9 * * *" />
        <div class="preset-row"><el-button v-for="[expr, label] in cronPresets" :key="expr" size="small" @click="form.cron = expr">{{ label }}</el-button></div>
        <p class="muted">保存后显示下次执行时间；应用关闭期间的运行不会补跑。</p>
      </template>
      <div class="panel-actions"><el-button type="primary" :disabled="pending" @click="perform(save)">保存</el-button><el-button @click="tab = 'list'">取消</el-button></div>
    </div>

    <div v-else-if="tab === 'history'" class="history">
      <el-empty v-if="!schedules.some(s => s.runs.length)" description="还没有运行记录。" :image-size="60" />
      <div v-for="s in schedules.filter(x => x.runs.length)" :key="s.id" class="history-block">
        <h3>{{ s.name }}</h3>
        <div v-for="run in [...s.runs].reverse()" :key="run.run_id" class="run-card">
          <div class="run-head"><el-tag :type="runStates[run.status] || 'info'">{{ runStatusLabels[run.status] || run.status }}</el-tag><span>{{ run.trigger === 'manual' ? '手动' : '定时' }} · {{ fmt(run.started_at) }} → {{ fmt(run.finished_at) }}</span><span class="muted">{{ run.succeeded }}/{{ run.total }} 成功{{ run.failed ? ` · ${run.failed} 失败` : '' }}</span></div>
          <el-table v-if="run.items.length" :data="run.items" size="small" stripe>
            <el-table-column prop="input" label="输入文件" min-width="160" />
            <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="runStates[row.status] || 'info'" size="small">{{ runStatusLabels[row.status] || row.status }}</el-tag></template></el-table-column>
            <el-table-column label="输出 / 错误" min-width="220"><template #default="{ row }"><span v-if="row.status === 'succeeded'" class="muted">{{ row.outputs.map((o: any) => o.name).join('、') }}</span><span v-else class="muted">{{ row.error || '—' }}</span></template></el-table-column>
          </el-table>
        </div>
      </div>
    </div>
    <el-alert v-if="message" :title="message" :type="pending ? 'info' : messageType" :closable="false" show-icon />
  </el-drawer>
</template>

<style scoped>
.panel-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.panel-actions .el-button { margin-left: 0; }
.run-banner { margin: 12px 0; }
.schedule-form { display: flex; flex-direction: column; gap: 10px; max-width: 640px; }
.folder-row { display: flex; gap: 8px; }
.folder-row .el-input { flex: 1; }
.preset-row { display: flex; flex-wrap: wrap; gap: 8px; }
.history-block { margin: 14px 0; }
.run-card { border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin: 8px 0; }
.run-head { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }
</style>
