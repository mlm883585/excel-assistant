import { ppx } from 'ppx-js'

export const call = <T = any>(method: string, params: unknown = {}) => ppx.call<T>(method, params, { timeoutMs: 60000 })
export type Selection = { file_id: string; sheet: string | number; header_row: number }
export type FileInfo = { id: string; name: string; kind?: string; statistics?: Record<string, unknown>; issues?: Record<string, unknown>[] }
export type Task = { id: string; status: string; files: FileInfo[]; outputs: FileInfo[]; error?: string }
export type TaskSummary = { id: string; name: string; status: string }
export type TaskEvent = { id: number; kind: string; data: any }
export const statusLabels: Record<string, string> = { pending: '待处理', running: '处理中', waiting: '等待回答', succeeded: '已完成', failed: '需处理', cancelled: '已取消' }
