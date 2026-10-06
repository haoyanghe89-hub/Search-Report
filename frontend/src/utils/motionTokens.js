export function tokenValue(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

export function tokenDuration(name, fallback = 0) {
  const value = tokenValue(name)
  if (value.endsWith('ms')) return Number.parseFloat(value) / 1000
  if (value.endsWith('s')) return Number.parseFloat(value)
  return Number.parseFloat(value) || fallback
}

export function tokenLength(name, fallback = 0) {
  return Number.parseFloat(tokenValue(name)) || fallback
}

export function tokenNumber(name, fallback = 0) {
  return Number.parseFloat(tokenValue(name)) || fallback
}

export function tokenEase(name, fallback = 'power2.out') {
  return tokenValue(name) || fallback
}
