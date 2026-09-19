import { ppx } from 'ppx-js'

export const call = <T = any>(method: string, params: unknown = {}) => ppx.call<T>(method, params, { timeoutMs: 60000 })
export type Selection = { file_id: string; sheet: string | number; header_row: number }
export type PivotPreview = { columns: string[]; rows: Record<string, unknown>[]; total: number }
export type ChartData = { type: string; title?: string; category: string; labels: (string | number)[]; series: { name: string; values: number[] }[] }
export type FileInfo = { id: string; name: string; kind?: string; statistics?: Record<string, unknown>; issues?: Record<string, unknown>[]; chart?: ChartData }
export type Task = { id: string; status: string; files: FileInfo[]; outputs: FileInfo[]; error?: string }
export type TaskSummary = { id: string; name: string; status: string }
export type TaskEvent = { id: number; kind: string; data: any }
export type Recipe = { id: string; name: string; plan: unknown; slots: string[] }
export type ScheduleTrigger = { type: 'manual' } | { type: 'cron'; cron: string }
export type RunItem = { input: string; status: string; outputs: { name: string; path: string }[]; error: string | null; task_id: string | null; finished_at: string | null }
export type RunRecord = { run_id: string; trigger: string; started_at: string; finished_at: string | null; status: string; total: number; succeeded: number; failed: number; items: RunItem[] }
export type Schedule = { id: string; name: string; recipe_id: string; recipe_name: string | null; source_dir: string; output_dir: string; trigger: ScheduleTrigger; enabled: boolean; created_at: string; last_run_at: string | null; next_run_at: string | null; runs: RunRecord[] }
export type AutomationStatus = { active: RunRecord | null; queue_len: number }
export type UpdateInfo = { version: string; base_url: string; enabled: boolean }
export type UpdateStatus = { update_available: boolean; current_version: string; latest_version?: string; url?: string; sha256?: string; size_bytes?: number; notes?: string; published_at?: string; reason?: string; error?: string }
export const statusLabels: Record<string, string> = { pending: '待处理', running: '处理中', waiting: '等待回答', succeeded: '已完成', failed: '需处理', cancelled: '已取消' }
export const runStatusLabels: Record<string, string> = { running: '运行中', succeeded: '成功', failed: '失败', partial: '部分成功', cancelled: '已取消' }
