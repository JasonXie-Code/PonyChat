export function filterDays(days, { query = '', month = '' } = {}) {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  return days.filter(entry => {
    if (month && !entry.date.startsWith(month)) return false
    const searchable = `${entry.date} ${entry.items.join(' ')}`.toLocaleLowerCase()
    return words.every(word => searchable.includes(word))
  })
}
