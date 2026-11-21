<template>
  <div class="bg-layer" aria-hidden="true" />
  <div class="shell shell-archive">
    <SiteHeader />
    <main class="archive-main">
      <article class="archive-md changelog">
        <p class="eyebrow">PONYCHAT / CHANGELOG</p>
        <h1>{{ t('updatesTitle') }}</h1>
        <p>{{ t('updatesLead') }}</p>
        <p v-if="history" class="history-meta">
          <time :datetime="history.days.at(-1).date">{{ history.days.at(-1).date }}</time><span>—</span><time :datetime="history.through">{{ history.through }}</time>
          <span>· {{ history.days.length }} {{ t('logDayUnit') }}</span>
        </p>
        <div class="log-jumps" role="group" :aria-label="t('logView')">
          <button class="log-button" :aria-pressed="view === 'daily'" @click="view = 'daily'">{{ t('logDaily') }}</button>
          <button class="log-button" :aria-pressed="view === 'monthly'" @click="view = 'monthly'">{{ t('logOverview') }}</button>
        </div>
        <section v-if="view === 'monthly'" id="overview">
          <h2>{{ t('logOverview') }}</h2><p>{{ t('logSummaryNote') }}</p>
          <div class="timeline">
            <section v-for="period in overview" :key="period.month" class="period">
              <p class="month-label"><time :datetime="period.month">{{ period.month }}</time></p>
              <h3>{{ period.title }}</h3><ul><li v-for="item in period.items" :key="item">{{ item }}</li></ul>
            </section>
          </div>
        </section>
        <section v-else id="daily">
          <h2>{{ t('logDaily') }}</h2><p>{{ t('logDailyNote') }}</p>
          <p v-if="loading" role="status">{{ t('loading') }}</p>
          <div v-else-if="error" role="alert"><p>{{ t('logLoadError') }}</p><button class="log-button" @click="loadHistory">{{ t('refresh') }}</button></div>
          <template v-else-if="history">
            <div class="log-filters">
              <label>{{ t('logSearch') }}<input v-model="query" type="search" :placeholder="t('logSearchHint')" /></label>
              <label>{{ t('logMonth') }}<select v-model="month"><option value="">{{ t('logAllMonths') }}</option><option v-for="value in months" :key="value">{{ value }}</option></select></label>
            </div>
            <p class="history-meta" role="status">{{ filtered.length }} {{ t('logDayMatches') }}</p>
            <p v-if="!filtered.length">{{ t('logEmpty') }}</p>
            <div class="timeline daily-timeline">
              <section v-for="entry in visible" :key="entry.date" class="period daily-entry">
                <h3><time :datetime="entry.date">{{ entry.date }}</time></h3>
                <p v-if="entry.earlySource" class="history-meta">{{ t('logEarlyLabel') }}</p>
                <ul><li v-for="item in entry.items" :key="item">{{ item }}</li></ul>
              </section>
            </div>
            <nav v-if="pages > 1" class="pagination" :aria-label="t('logPagination')">
              <button class="log-button" :disabled="page === 1" @click="page--">{{ t('logPrevious') }}</button><span>{{ page }} / {{ pages }}</span><button class="log-button" :disabled="page === pages" @click="page++">{{ t('logNext') }}</button>
            </nav>
          </template>
        </section>
        <p class="log-footnote">{{ t('logHistoryNote') }}</p>
      </article>
    </main>
    <SiteFooter />
  </div>
</template>
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import SiteHeader from '../components/SiteHeader.vue'
import SiteFooter from '../components/SiteFooter.vue'
import { useSiteI18n } from '../i18n/index.js'
import overview from '../content/changelog-overview.json'
import { filterDays } from '../content/changelog.js'
import '../styles/changelog.css'
const { t } = useSiteI18n()
const history = ref(null)
const loading = ref(true)
const error = ref(false)
const view = ref('daily')
const query = ref('')
const month = ref('')
const page = ref(1)
const pageSize = 10
const months = computed(() => [...new Set((history.value?.days || []).map(entry => entry.date.slice(0, 7)))])
const filtered = computed(() => filterDays(history.value?.days || [], { query: query.value, month: month.value }))
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const visible = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch([query, month], () => { page.value = 1 })
async function loadHistory() {
  loading.value = true
  error.value = false
  try {
    const response = await fetch('/changelog/history.json', { cache: 'no-cache' })
    if (!response.ok) throw new Error('History unavailable')
    const result = await response.json()
    if (!Array.isArray(result.days) || !result.days.length || !result.days.every(day => day.date && Array.isArray(day.items) && day.items.length)) throw new Error('Invalid history')
    history.value = result
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}
onMounted(loadHistory)
</script>
