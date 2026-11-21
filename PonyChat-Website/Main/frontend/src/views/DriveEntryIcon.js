import { h } from 'vue'
import { iconMetaForEntry } from './driveViewModel.js'

export default function DriveEntryIcon(props) {
  const meta = iconMetaForEntry(props.entry)
  if (meta.badge) {
    return h(
      'span',
      { class: ['drive-entry-icon', 'drive-file-badge', meta.className], title: meta.title },
      [
        h('span', { class: 'drive-file-badge-mark', 'aria-hidden': 'true' }, meta.badge),
        h('span', { class: 'drive-file-badge-fold', 'aria-hidden': 'true' }),
      ],
    )
  }
  return h(
    'span',
    { class: ['drive-entry-icon', 'drive-file-symbol', meta.className], title: meta.title },
    [h('ion-icon', { name: meta.icon, 'aria-hidden': 'true' })],
  )
}
