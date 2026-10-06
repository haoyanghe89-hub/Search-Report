import { readonly, ref } from 'vue'

const STORAGE_KEY = 'search-report-theme'
const DARK_MEDIA_QUERY = '(prefers-color-scheme: dark)'
const VALID_THEMES = new Set(['light', 'dark'])

const theme = ref('dark')
let initialized = false

function readStoredTheme() {
  try {
    const storedTheme = window.localStorage.getItem(STORAGE_KEY)
    return VALID_THEMES.has(storedTheme) ? storedTheme : null
  } catch {
    return null
  }
}

function applyTheme(nextTheme) {
  theme.value = nextTheme
  document.documentElement.dataset.theme = nextTheme
}

function initializeTheme() {
  if (initialized || typeof window === 'undefined' || typeof document === 'undefined') {
    return
  }

  initialized = true
  const colorScheme = window.matchMedia(DARK_MEDIA_QUERY)
  applyTheme(readStoredTheme() ?? 'dark')

  colorScheme.addEventListener('change', (event) => {
    if (!readStoredTheme()) {
      applyTheme(event.matches ? 'dark' : 'light')
    }
  })
}

function setTheme(nextTheme) {
  if (!VALID_THEMES.has(nextTheme)) {
    return
  }

  applyTheme(nextTheme)

  try {
    window.localStorage.setItem(STORAGE_KEY, nextTheme)
  } catch {
    // The active theme still applies when storage is unavailable.
  }
}

function toggleTheme() {
  setTheme(theme.value === 'dark' ? 'light' : 'dark')
}

export function useTheme() {
  initializeTheme()

  return {
    theme: readonly(theme),
    setTheme,
    toggleTheme,
  }
}
