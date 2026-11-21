import { marked } from 'marked'

const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
const renderer = new marked.Renderer()
renderer.html = (html) => escape(html)
renderer.link = (href, title, text) => {
  try {
    const url = new URL(href, 'https://www.ponychat.org')
    if (!['http:', 'https:', 'mailto:'].includes(url.protocol)) return text
    return `<a href="${escape(url.href)}" target="_blank" rel="noopener noreferrer"${title ? ` title="${escape(title)}"` : ''}>${text}</a>`
  } catch { return text }
}
renderer.image = (_href, _title, text) => escape(text)

export function creationMarkdown(value) {
  return marked.parse(String(value ?? ''), { renderer, gfm: true, breaks: true, async: false })
}
