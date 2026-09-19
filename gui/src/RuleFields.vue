<script setup lang="ts">
import { ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
const props = defineProps<{ kind: string; fields: string[]; busy: boolean }>()
const name = ref(''), first = ref(''), second = ref(''), operator = ref('multiply'), constant = ref(0), useConstant = ref(false), digits = ref(2)
const defaultLabel = ref('普通'), rules = ref([{ threshold: 100, label: '高' }]), tableName = ref('填报表'), headers = ref('编号，名称，数量，备注')
function params() {
  if (props.kind === 'create_table') return { name: tableName.value, sheet_name: tableName.value, columns: headers.value.split(/[,，\n]/).map(s => s.trim()).filter(Boolean), blank_rows: 20 }
  if (!name.value.trim() || !first.value) throw new Error('请填写新字段名称及依据字段')
  if (props.kind === 'calculate') {
    if (!useConstant.value && !second.value) throw new Error('请选择第二个计算字段')
    const expression = { op: operator.value, args: [{ field: first.value }, useConstant.value ? { number: constant.value } : { field: second.value }] }
    return { columns: [{ name: name.value.trim(), expression: { op: 'round', args: [expression, { number: digits.value }] } }] }
  }
  return { columns: [{ name: name.value.trim(), rules: rules.value.map(r => ({ when: { field: first.value, operator: 'ge', value: r.threshold }, label: r.label })), default: defaultLabel.value }] }
}
defineExpose({ params })
</script>
<template>
  <div v-if="kind==='create_table'"><label class="field-label">工作表名称</label><el-input v-model="tableName" :disabled="busy" aria-label="新表名称"/><label class="field-label">表头字段（逗号或换行分隔）</label><el-input v-model="headers" type="textarea" :rows="3" :disabled="busy" aria-label="新表字段"/><p class="muted">生成 20 行空白填报区域；需要填入明确数据时，可用文字描述。</p></div>
  <template v-else><label class="field-label">新增字段名称</label><el-input v-model="name" :disabled="busy" aria-label="新增字段名称"/><label class="field-label">{{kind==='calculate'?'计算字段':'分级依据'}}</label><el-select v-model="first" :disabled="busy" aria-label="规则依据字段"><el-option v-for="f in fields" :key="f" :value="f"/></el-select>
    <template v-if="kind==='calculate'"><label class="field-label">运算</label><el-select v-model="operator" :disabled="busy" aria-label="计算方式"><el-option v-for="(label,key) in {add:'加',subtract:'减',multiply:'乘',divide:'除'}" :key="key" :value="key" :label="label"/></el-select><el-checkbox v-model="useConstant" :disabled="busy">使用固定数值</el-checkbox><el-input-number v-if="useConstant" v-model="constant" :disabled="busy" aria-label="计算常数"/><el-select v-else v-model="second" :disabled="busy" aria-label="第二个计算字段"><el-option v-for="f in fields" :key="f" :value="f"/></el-select><label class="field-label">小数位数</label><el-input-number v-model="digits" :min="0" :max="15" :disabled="busy"/></template>
    <template v-else><p class="muted">按以下顺序匹配，满足首条即写入等级；请把高门槛放在前面。</p><div v-for="(rule,i) in rules" :key="i" class="classification-rule"><span>≥</span><el-input-number v-model="rule.threshold" :disabled="busy" aria-label="分级门槛"/><el-input v-model="rule.label" :disabled="busy" aria-label="分级标签"/><el-button :disabled="busy || rules.length===1" @click="rules.splice(i,1)">删除</el-button></div><el-button :disabled="busy" :icon="Plus" @click="rules.push({threshold:0,label:''})">条件</el-button><label class="field-label">其余记录标记为</label><el-input v-model="defaultLabel" :disabled="busy" aria-label="默认等级"/></template>
  </template>
</template>
<style scoped>.classification-rule{display:flex;gap:6px;align-items:center;margin:8px 0;flex-wrap:wrap}.classification-rule .el-input{width:90px}</style>
