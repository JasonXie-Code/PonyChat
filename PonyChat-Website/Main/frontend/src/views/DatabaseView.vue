<template>
  <div class="bg-layer" aria-hidden="true" />
  <div class="database-shell">
    <header class="site-header database-header">
      <RouterLink class="brand" to="/">
        <img :src="logo" alt="" class="logo-img" width="44" height="44" decoding="async">
        <span class="brand-text">PonyChat</span>
      </RouterLink>
      <nav class="header-nav" aria-label="页面导航">
        <RouterLink to="/app">网页聊天</RouterLink>
        <RouterLink to="/character-hall">角色大厅</RouterLink>
        <RouterLink to="/">首页</RouterLink>
      </nav>
    </header>

    <main class="database-main">
      <section class="database-toolbar" aria-labelledby="database-title">
        <div class="database-title-block">
          <p class="database-kicker">G4 S1-S3 · World Database</p>
          <h1 id="database-title">小马世界资料库</h1>
        </div>
        <div class="database-stats" aria-label="数据库统计">
          <div v-for="item in statItems" :key="item.key" class="database-stat">
            <span class="database-stat-value">{{ item.value }}</span>
            <span class="database-stat-label">{{ item.label }}</span>
          </div>
        </div>
      </section>

      <section class="database-layout">
        <form class="query-card" @submit.prevent="runQuery">
          <label class="field-label" for="database-query">关键词</label>
          <textarea
            id="database-query"
            v-model="queryText"
            class="query-input"
            rows="4"
            placeholder="紫色聪明, 小马镇"
            spellcheck="false"
          />

          <div class="sample-strip" aria-label="示例查询">
            <button
              v-for="sample in samples"
              :key="sample"
              type="button"
              class="sample-chip"
              @click="useSample(sample)"
            >
              {{ sample }}
            </button>
          </div>

          <div class="query-controls">
            <label class="budget-control" for="budget">
              <span>每词预算</span>
              <select id="budget" v-model.number="budget">
                <option :value="180">180 字</option>
                <option :value="300">300 字</option>
                <option :value="500">500 字</option>
              </select>
            </label>
            <button class="icon-button" type="button" title="清空" aria-label="清空" @click="clearQuery">
              <ion-icon name="close-outline" aria-hidden="true" />
            </button>
            <button class="primary-button" type="submit" :disabled="loading || !queryText.trim()">
              <ion-icon name="search-outline" aria-hidden="true" />
              <span>{{ loading ? '查询中' : '查询' }}</span>
            </button>
          </div>

          <div class="type-grid" aria-label="条目类型统计">
            <div v-for="item in typeItems" :key="item.type" class="type-pill">
              <span>{{ typeName(item.type) }}</span>
              <strong>{{ item.count }}</strong>
            </div>
          </div>
        </form>

        <section class="result-stage" aria-live="polite">
          <div v-if="error" class="state-card state-card-error">
            <ion-icon name="alert-circle-outline" aria-hidden="true" />
            <span>{{ error }}</span>
          </div>

          <div v-else-if="!result" class="state-card">
            <ion-icon name="file-tray-stacked-outline" aria-hidden="true" />
            <span>等待查询</span>
          </div>

          <template v-else>
            <div class="result-head">
              <div>
                <p class="result-kicker">Query</p>
                <h2>{{ result.query }}</h2>
              </div>
              <button class="icon-button" type="button" title="复制素材" aria-label="复制素材" @click="copyResult">
                <ion-icon name="copy-outline" aria-hidden="true" />
              </button>
            </div>

            <article v-for="item in result.results" :key="item.term" class="result-card">
              <div class="result-card-head">
                <div>
                  <p class="result-term">{{ item.term }}</p>
                  <h3>{{ item.resolved_to || '未命中' }}</h3>
                </div>
                <span v-if="item.matches?.[0]" class="type-badge">{{ typeName(item.matches[0].entity_type) }}</span>
              </div>

              <div class="material-list">
                <section v-for="block in materialBlocks(item.material)" :key="block.label + block.body" class="material-block">
                  <p class="material-label">{{ block.label }}</p>
                  <p class="material-body">{{ block.body }}</p>
                </section>
                <p v-if="!item.material" class="material-empty">未命中本地 S1-S3 资料。</p>
              </div>

              <div v-if="item.matches?.length" class="alias-row">
                <span v-for="match in item.matches" :key="match.canonical_name + match.match_type" class="alias-chip">
                  {{ match.canonical_name }}
                </span>
              </div>
            </article>

            <article v-if="result.relation_material" class="result-card relation-card">
              <div class="result-card-head">
                <div>
                  <p class="result-term">交集素材</p>
                  <h3>关键词关系</h3>
                </div>
                <span class="type-badge type-badge-warm">Context</span>
              </div>
              <div class="material-list">
                <section v-for="block in materialBlocks(result.relation_material)" :key="block.label + block.body" class="material-block">
                  <p class="material-label">{{ block.label }}</p>
                  <p class="material-body">{{ block.body }}</p>
                </section>
              </div>
            </article>
          </template>
        </section>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { usePublicUrl } from '../composables/usePublicUrl.js'

const pub = usePublicUrl()
const logo = pub('logo/logoBK512.png')

const queryText = ref('紫色聪明, 小马镇')
const budget = ref(300)
const loading = ref(false)
const error = ref('')
const result = ref(null)
const stats = ref(null)

const samples = [
  '紫色聪明, 小马镇',
  '可爱标记, 小马镇学校',
  '云宝, 云中城',
  'Twilight Sparkle, Elements of Harmony',
  'Applejack, Sweet Apple Acres',
]

const typeLabels = {
  character: '角色',
  location: '地点',
  concept: '设定',
  episode: '剧集',
  song: '歌曲',
  item: '物品',
  species: '种族',
}

const statItems = computed(() => [
  { key: 'entries', label: '条目', value: stats.value?.entries ?? '—' },
  { key: 'aliases', label: '别名', value: stats.value?.aliases ?? '—' },
  { key: 'episodes', label: '剧集', value: stats.value?.episodes ?? '—' },
  { key: 'facts', label: '素材', value: stats.value?.facts ?? '—' },
])

const typeItems = computed(() => stats.value?.by_type || [])

function typeName(type) {
  return typeLabels[type] || type || '未知'
}

function materialBlocks(material) {
  if (!material) return []
  return String(material)
    .split(/\n{2,}/)
    .map((block) => {
      const lines = block.split('\n')
      return {
        label: lines[0] || '资料',
        body: lines.slice(1).join('\n').trim() || lines[0] || '',
      }
    })
    .filter((block) => block.body)
}

async function loadStats() {
  try {
    const res = await fetch('/api/mlp-database/stats')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    stats.value = await res.json()
  } catch (_) {
    stats.value = null
  }
}

async function runQuery() {
  const query = queryText.value.trim()
  if (!query) return
  loading.value = true
  error.value = ''
  try {
    const res = await fetch('/api/mlp-database/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, budget: budget.value }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
    result.value = data
  } catch (err) {
    error.value = err?.message || '查询失败'
  } finally {
    loading.value = false
  }
}

function useSample(sample) {
  queryText.value = sample
  runQuery()
}

function clearQuery() {
  queryText.value = ''
  result.value = null
  error.value = ''
}

async function copyResult() {
  if (!result.value) return
  const chunks = []
  for (const item of result.value.results || []) {
    chunks.push(`## ${item.term}\n${item.material || '未命中本地 S1-S3 资料。'}`)
  }
  if (result.value.relation_material) {
    chunks.push(`## 关键词关系/交集\n${result.value.relation_material}`)
  }
  await navigator.clipboard?.writeText(chunks.join('\n\n'))
}

onMounted(() => {
  loadStats()
  runQuery()
})
</script>

<style scoped>
.database-shell {
  position: relative;
  z-index: 1;
  max-width: 1240px;
  min-height: 100dvh;
  margin: 0 auto;
  padding: max(22px, env(safe-area-inset-top, 0px)) clamp(16px, 4vw, 40px) 42px;
  color: var(--text);
}

.database-header {
  margin-bottom: clamp(22px, 4vw, 36px);
}

.database-main {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.database-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: end;
}

.database-kicker,
.result-kicker,
.result-term {
  color: #7dd3c7;
  font-size: 0.74rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.database-title-block h1,
.result-head h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(1.8rem, 4vw, 2.8rem);
  line-height: 1.1;
  letter-spacing: 0;
}

.database-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(76px, 1fr));
  gap: 8px;
}

.database-stat,
.query-card,
.result-card,
.state-card {
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.72);
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.22);
}

.database-stat {
  padding: 11px 12px;
}

.database-stat-value {
  display: block;
  color: #f8fafc;
  font-family: var(--font-display);
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1;
}

.database-stat-label {
  color: var(--text-muted);
  font-size: 0.76rem;
}

.database-layout {
  display: grid;
  grid-template-columns: minmax(300px, 0.82fr) minmax(0, 1.48fr);
  gap: 16px;
  align-items: start;
}

.query-card {
  position: sticky;
  top: 18px;
  padding: 16px;
}

.field-label {
  display: block;
  margin-bottom: 8px;
  color: #cbd5e1;
  font-weight: 700;
}

.query-input {
  width: 100%;
  min-height: 128px;
  resize: vertical;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.6);
  color: #f8fafc;
  padding: 13px 14px;
  font: inherit;
  line-height: 1.6;
  outline: none;
}

.query-input:focus {
  border-color: rgba(125, 211, 199, 0.64);
  box-shadow: 0 0 0 3px rgba(125, 211, 199, 0.12);
}

.sample-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0 14px;
}

.sample-chip,
.alias-chip,
.type-pill,
.type-badge {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 999px;
  background: rgba(30, 41, 59, 0.7);
  color: #cbd5e1;
}

.sample-chip {
  min-height: 32px;
  padding: 0 10px;
  font: inherit;
  font-size: 0.82rem;
  cursor: pointer;
}

.sample-chip:hover {
  border-color: rgba(244, 114, 182, 0.38);
  color: #fce7f3;
}

.query-controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 42px auto;
  gap: 8px;
  align-items: end;
}

.budget-control {
  display: grid;
  gap: 5px;
  color: var(--text-muted);
  font-size: 0.78rem;
  font-weight: 700;
}

.budget-control select {
  height: 42px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.7);
  color: #e2e8f0;
  padding: 0 10px;
  font: inherit;
}

.primary-button,
.icon-button {
  height: 42px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  color: #f8fafc;
  cursor: pointer;
}

.primary-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 16px;
  background: linear-gradient(135deg, #7c3aed 0%, #0d9488 100%);
  font: inherit;
  font-weight: 700;
}

.primary-button:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.icon-button {
  display: inline-grid;
  place-items: center;
  width: 42px;
  background: rgba(30, 41, 59, 0.76);
  font-size: 1.25rem;
}

.icon-button:hover,
.primary-button:hover:not(:disabled) {
  border-color: rgba(125, 211, 199, 0.48);
  filter: brightness(1.07);
}

.type-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.type-pill {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  font-size: 0.82rem;
}

.type-pill strong {
  color: #fde68a;
}

.result-stage {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.state-card {
  min-height: 220px;
  display: grid;
  place-items: center;
  gap: 10px;
  padding: 28px;
  color: var(--text-muted);
  text-align: center;
}

.state-card ion-icon {
  color: #7dd3c7;
  font-size: 2rem;
}

.state-card-error {
  color: #fecaca;
}

.state-card-error ion-icon {
  color: #fb7185;
}

.result-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 4px 2px 2px;
}

.result-head h2 {
  font-size: clamp(1.25rem, 2.6vw, 1.75rem);
  word-break: break-word;
}

.result-card {
  padding: 16px;
}

.result-card-head {
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 12px;
  margin-bottom: 12px;
}

.result-card h3 {
  margin: 2px 0 0;
  color: #f8fafc;
  font-family: var(--font-display);
  font-size: 1.2rem;
  letter-spacing: 0;
}

.type-badge {
  flex: 0 0 auto;
  padding: 5px 9px;
  color: #bae6fd;
  font-size: 0.74rem;
  font-weight: 700;
}

.type-badge-warm {
  color: #fed7aa;
}

.material-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.material-block {
  border-left: 3px solid rgba(125, 211, 199, 0.58);
  padding: 2px 0 2px 11px;
}

.material-label {
  margin: 0 0 6px;
  color: #c4b5fd;
  font-size: 0.82rem;
  font-weight: 700;
  word-break: break-word;
}

.material-body,
.material-empty {
  margin: 0;
  color: #dbeafe;
  font-size: 0.94rem;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.material-empty {
  color: var(--text-muted);
}

.alias-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
}

.alias-chip {
  padding: 4px 8px;
  color: #d1fae5;
  font-size: 0.76rem;
}

.relation-card {
  border-color: rgba(251, 191, 36, 0.2);
  background: rgba(30, 27, 75, 0.62);
}

@media (max-width: 940px) {
  .database-toolbar,
  .database-layout {
    grid-template-columns: 1fr;
  }

  .database-stats {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .query-card {
    position: static;
  }
}

@media (max-width: 560px) {
  .database-shell {
    padding-inline: 14px;
  }

  .database-header {
    align-items: flex-start;
  }

  .database-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .query-controls {
    grid-template-columns: minmax(0, 1fr) 42px;
  }

  .primary-button {
    grid-column: 1 / -1;
    width: 100%;
  }

  .type-grid {
    grid-template-columns: 1fr;
  }
}
</style>
