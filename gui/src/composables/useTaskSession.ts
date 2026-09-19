import { computed, onBeforeUnmount, ref } from 'vue'
import { call, type Task, type TaskEvent, type TaskSummary } from '../rpc'

type TaskPage = { task: Task; events: TaskEvent[] }
type EventPage = { items: TaskEvent[]; has_more: boolean }
type Recipe = { id: string; name: string; slots: unknown[] }
type Options = {
  beforeSelect: () => Promise<void>
  reset: () => void
  selected: (task: Task) => Promise<void>
  questioned: () => void
  finished: (task: Task) => void
  report: (error: unknown) => void
}

export function useTaskSession(options: Options) {
  const task = ref<Task>()
  const history = ref<TaskSummary[]>([])
  const historyOffset = ref(0)
  const moreTasks = ref(false)
  const recipes = ref<Recipe[]>([])
  const events = ref<TaskEvent[]>([])
  const moreEvents = ref(false)
  const viewingOlder = ref(false)
  const cursor = ref(0)
  const loading = ref(true)
  const question = ref<TaskEvent['data']>(null)
  const answers = ref<Record<string, string>>({})
  const busy = computed(() => ['running', 'waiting'].includes(task.value?.status || ''))
  let generation = 0, listGeneration = 0, eventGeneration = 0, disposed = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let activePoll: { generation: number; promise: Promise<void> } | undefined

  // Every async operation captures the task generation before its first await.
  function capture() {
    const current = generation
    return () => !disposed && current === generation
  }

  async function refreshLists(nextPage = false) {
    const request = ++listGeneration
    const offset = nextPage ? historyOffset.value + 30 : 0
    const [page, saved] = await Promise.all([
      call<{ items: TaskSummary[]; has_more: boolean }>('tasks.summaries', { offset, limit: 30 }),
      nextPage ? Promise.resolve(undefined) : call<Recipe[]>('recipes.list'),
    ])
    if (disposed || request !== listGeneration) return
    historyOffset.value = offset
    history.value = page.items
    moreTasks.value = page.has_more
    if (saved) recipes.value = saved
  }

  function updateQuestion(items: TaskEvent[], notify = false) {
    for (const event of items) {
      if (event.kind !== 'question') continue
      question.value = event.data
      answers.value = {}
      if (notify) options.questioned()
    }
    if (task.value?.status !== 'waiting') question.value = null
  }

  async function selectTask(id: string) {
    ++generation
    ++eventGeneration
    const current = capture()
    clearTimeout(timer)
    try {
      await options.beforeSelect()
      if (!current()) return
      options.reset()
      loading.value = true
      task.value = undefined
      events.value = []
      question.value = null
      answers.value = {}
      viewingOlder.value = false
      const [record, page] = await Promise.all([
        call<TaskPage>('tasks.get', { task_id: id, after: Number.MAX_SAFE_INTEGER }),
        call<EventPage>('tasks.events', { task_id: id }),
      ])
      if (!current()) return
      task.value = record.task
      events.value = page.items
      moreEvents.value = page.has_more
      cursor.value = page.items.at(-1)?.id || 0
      updateQuestion(page.items)
      loading.value = false
      await options.selected(record.task)
    } finally {
      if (current()) { loading.value = false; schedule() }
    }
  }

  function schedule() {
    clearTimeout(timer)
    if (!disposed && busy.value) {
      const delay = document.hidden ? 5000 : task.value?.status === 'waiting' ? 3000 : 400
      timer = setTimeout(() => void fetchUpdates().catch(options.report), delay)
    }
  }

  async function fetchUpdates() {
    if (!task.value || disposed) return
    if (activePoll?.generation === generation) return activePoll.promise
    const current = capture(), id = task.value.id
    const request = { generation, promise: Promise.resolve() }
    request.promise = (async () => {
      try {
        let result: TaskPage
        do {
          result = await call<TaskPage>('tasks.get', { task_id: id, after: cursor.value })
          if (!current()) return
          const previous = task.value!.status
          task.value = result.task
          if (result.events.length) {
            cursor.value = result.events.at(-1)!.id
            if (!viewingOlder.value) {
              const combined = [...events.value, ...result.events]
              moreEvents.value ||= combined.length > 200
              events.value = combined.slice(-200)
            }
          }
          updateQuestion(result.events, true)
          if (previous !== task.value.status && !busy.value) {
            options.finished(task.value)
            await refreshLists()
            if (!current()) return
          }
        } while (result.events.length === 200 && !busy.value)
      } finally {
        if (activePoll === request) activePoll = undefined
        if (current()) schedule()
      }
    })()
    activePoll = request
    return request.promise
  }

  // Actions need a fresh response even if a pre-action poll is already in flight.
  async function poll() {
    const current = capture()
    if (activePoll?.generation === generation) await activePoll.promise
    if (current()) await fetchUpdates()
  }

  async function loadEvents(older: boolean) {
    if (!task.value) return
    const current = capture(), request = ++eventGeneration
    const page = await call<EventPage>('tasks.events', {
      task_id: task.value.id, ...(older ? { before: events.value[0]?.id } : {}),
    })
    if (!current() || request !== eventGeneration) return
    events.value = page.items
    moreEvents.value = page.has_more
    viewingOlder.value = older
  }

  function visible() {
    if (!document.hidden && busy.value) {
      clearTimeout(timer)
      void fetchUpdates().catch(options.report)
    }
  }
  document.addEventListener('visibilitychange', visible)
  onBeforeUnmount(() => {
    disposed = true
    ++generation
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', visible)
  })
  return {
    task, history, historyOffset, moreTasks, recipes, events, moreEvents, viewingOlder,
    cursor, loading, question, answers, busy, capture, refreshLists, selectTask, poll,
    older: () => loadEvents(true), latest: () => loadEvents(false),
  }
}
