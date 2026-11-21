import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { filterDays } from '../src/content/changelog.js'
const history = JSON.parse(readFileSync(new URL('../public/changelog/history.json', import.meta.url), 'utf8'))

test('daily history covers every reachable commit and skips days without records', () => {
  const records = execFileSync('git', ['log', history.revision, '--format=%H%x09%cs'], { encoding: 'utf8' }).trim().split('\n').map(line => line.split('\t'))
  const hashes = records.map(([hash]) => hash)
  const published = history.days.flatMap(day => day.sources)
  assert.equal(history.count, hashes.length)
  assert.deepEqual([...published].sort(), hashes.sort())
  assert.equal(new Set(published).size, history.count)
  assert.equal(new Set(history.days.map(day => day.date)).size, history.days.length)
  assert.deepEqual(history.days.filter(day => day.sources.length).map(day => day.date), [...new Set(records.map(([, date]) => date))].sort().reverse())
  assert.equal(history.days.at(-1).date, '2026-04-11')
  assert.ok(history.days.every(day => day.items.length && day.items.every(item => /[\u4e00-\u9fff]/.test(item))))
  assert.ok(!JSON.stringify(history).includes('subject'))
})

test('daily search combines Chinese keywords, dates and month filters', () => {
  assert.equal(filterDays(history.days, { query: '2026-05-21' })[0].date, '2026-05-21')
  assert.deepEqual(filterDays(history.days, { query: '2026-05-21', month: '2026-10' }), [])
  const matches = filterDays(history.days, { query: '找图 语音', month: '2026-10' })
  assert.ok(matches.length)
  assert.ok(matches.every(day => day.date.startsWith('2026-10') && day.items.join(' ').includes('找图') && day.items.join(' ').includes('语音')))
  assert.deepEqual(filterDays(history.days, { query: 'no-such-record-123456' }), [])
  assert.equal(filterDays(history.days, { query: '   ' }).length, history.days.length)
})
