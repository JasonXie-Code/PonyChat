import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolveLocale, supportedLocales } from '../src/i18n/locale.js'

test('browser preferences take precedence over geography', () => {
  assert.equal(resolveLocale({ languages: ['ru-RU', 'en-US'], timeZone: 'Asia/Shanghai' }), 'ru')
  assert.equal(resolveLocale({ languages: ['en-GB', 'ru'], region: 'RU' }), 'en')
  assert.equal(resolveLocale({ languages: ['fr-FR', 'ru-RU'], region: 'FR' }), 'ru')
})

test('Chinese script and region variants', () => {
  for (const tag of ['zh-TW', 'zh-HK', 'zh-MO', 'zh-Hant', 'zh-Hant-CN']) {
    assert.equal(resolveLocale({ languages: [tag], region: 'CN' }), 'zh-TW', tag)
  }
  for (const tag of ['zh-CN', 'zh-SG', 'zh-Hans-HK']) {
    assert.equal(resolveLocale({ languages: [tag], region: 'TW' }), 'zh-CN', tag)
  }
  assert.equal(resolveLocale({ languages: ['zh'], timeZone: 'Asia/Taipei' }), 'zh-TW')
})

test('region/timezone fallback and international default', () => {
  assert.equal(resolveLocale({ languages: ['de-DE'], timeZone: 'Europe/Moscow' }), 'ru')
  assert.equal(resolveLocale({ languages: [], timeZone: 'Asia/Hong_Kong' }), 'zh-TW')
  assert.equal(resolveLocale({ languages: [], region: 'SG' }), 'zh-CN')
  assert.equal(resolveLocale({ languages: ['ja-JP'], timeZone: 'Asia/Tokyo' }), 'en')
  assert.equal(resolveLocale(), 'en')
})

test('explicit links and saved choices win, unsupported values are ignored', () => {
  assert.equal(resolveLocale({ explicit: 'ru', saved: 'en', languages: ['zh-CN'] }), 'ru')
  assert.equal(resolveLocale({ saved: 'zh-TW', languages: ['en'] }), 'zh-TW')
  assert.equal(resolveLocale({ explicit: 'invalid', saved: 'invalid', languages: ['en'] }), 'en')
})

test('every locale supplies the same nonempty translation keys', () => {
  const catalogs = supportedLocales.map((language) => JSON.parse(readFileSync(new URL(`../src/i18n/${language}.json`, import.meta.url))))
  const keys = Object.keys(catalogs[0]).sort()
  for (const catalog of catalogs) {
    assert.deepEqual(Object.keys(catalog).sort(), keys)
    for (const value of Object.values(catalog)) assert.equal(typeof value === 'string' && value.trim().length > 0, true)
  }
})
