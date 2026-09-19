import { ref } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'auto'

const STORAGE_KEY = 'excel-assistant-theme'
const MODES: ThemeMode[] = ['light', 'dark', 'auto']

function readSaved(): ThemeMode {
  const value = localStorage.getItem(STORAGE_KEY)
  return MODES.includes(value as ThemeMode) ? (value as ThemeMode) : 'auto'
}

export const themeMode = ref<ThemeMode>('auto')
export const isDark = ref(false)

const media = window.matchMedia('(prefers-color-scheme: dark)')

function resolveIsDark(mode: ThemeMode): boolean {
  return mode === 'dark' ? true : mode === 'light' ? false : media.matches
}

function apply() {
  isDark.value = resolveIsDark(themeMode.value)
  document.documentElement.classList.toggle('dark', isDark.value)
}

export function setThemeMode(mode: ThemeMode) {
  themeMode.value = mode
  localStorage.setItem(STORAGE_KEY, mode)
  apply()
}

export function initTheme() {
  themeMode.value = readSaved()
  apply()
  media.addEventListener('change', () => { if (themeMode.value === 'auto') apply() })
}
