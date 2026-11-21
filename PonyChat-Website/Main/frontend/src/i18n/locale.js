export const supportedLocales = ['zh-CN', 'zh-TW', 'en', 'ru']
export const languageOptions = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'zh-TW', label: '繁體中文' },
  { value: 'en', label: 'English' },
  { value: 'ru', label: 'Русский' },
]

export function regionLocale(region = '', timeZone = '') {
  const country = region.toUpperCase()
  if (['TW', 'HK', 'MO'].includes(country)) return 'zh-TW'
  if (['CN', 'SG'].includes(country)) return 'zh-CN'
  if (country === 'RU') return 'ru'
  if (['Asia/Taipei', 'Asia/Hong_Kong', 'Asia/Macau', 'Asia/Macao'].includes(timeZone)) return 'zh-TW'
  if (['Asia/Shanghai', 'Asia/Chongqing', 'Asia/Chungking', 'Asia/Harbin', 'Asia/Urumqi', 'Asia/Singapore'].includes(timeZone)) return 'zh-CN'
  if (/^(Europe\/(Moscow|Kaliningrad|Samara|Saratov|Ulyanovsk|Volgograd|Astrakhan)|Asia\/(Yekaterinburg|Omsk|Novosibirsk|Novokuznetsk|Barnaul|Tomsk|Krasnoyarsk|Irkutsk|Chita|Yakutsk|Vladivostok|Khandyga|Ust-Nera|Sakhalin|Magadan|Srednekolymsk|Kamchatka|Anadyr))$/.test(timeZone)) return 'ru'
  return 'en'
}

export function matchLanguage(tag, region = '', timeZone = '') {
  const value = String(tag || '').replaceAll('_', '-').toLowerCase()
  if (/^zh(?:-|$)/.test(value)) {
    // An explicit script takes precedence over the country (e.g. zh-Hans-HK).
    if (value.includes('-hant')) return 'zh-TW'
    if (value.includes('-hans')) return 'zh-CN'
    if (/-?(tw|hk|mo)$/.test(value)) return 'zh-TW'
    if (/-(cn|sg)$/.test(value)) return 'zh-CN'
    return regionLocale(region, timeZone) === 'zh-TW' ? 'zh-TW' : 'zh-CN'
  }
  if (/^ru(?:-|$)/.test(value)) return 'ru'
  if (/^en(?:-|$)/.test(value)) return 'en'
  return null
}

export function resolveLocale({ explicit, saved, languages = [], region = '', timeZone = '' } = {}) {
  if (supportedLocales.includes(explicit)) return explicit
  if (supportedLocales.includes(saved)) return saved
  for (const language of languages) {
    const matched = matchLanguage(language, region, timeZone)
    if (matched) return matched
  }
  return regionLocale(region, timeZone)
}
