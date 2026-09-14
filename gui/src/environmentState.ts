import { ref } from 'vue'

export type Check = { name: string; status: string; message: string; impact?: string; action?: string }
export type Candidate = { id: string; source: string; cli: string; node_executable: string; version: string; node_version: string; compatible: boolean; reason: string }
// Module lifetime is independent of drawer visibility and lazy component mounting.
export const checks = ref<Check[]>([]), candidates = ref<Candidate[]>([]), message = ref('')
export const pending = ref(false), runId = ref(''), kind = ref(''), selectedId = ref(''), initialized = ref(false)
export const messageType = ref<'success' | 'warning' | 'error' | 'info'>('info')
export const modelStatus = ref('未检测'), excelStatus = ref('未检测')
