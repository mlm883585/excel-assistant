import { ref } from 'vue'
import type { Schedule, Recipe, RunRecord } from './rpc'

// Module lifetime is independent of drawer visibility and lazy component mounting.
export const schedules = ref<Schedule[]>([]), recipes = ref<Recipe[]>([])
export const active = ref<RunRecord | null>(null), queueLen = ref(0)
export const pending = ref(false), initialized = ref(false)
export const message = ref(''), messageType = ref<'success' | 'warning' | 'error' | 'info'>('info')
