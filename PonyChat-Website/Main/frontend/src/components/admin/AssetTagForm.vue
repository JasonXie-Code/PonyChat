<template>
  <div class="tag-form">
    <label class="fld">
      <span>简介 <em class="hint">（一句话概括表情内容和核心情绪）</em></span>
      <input
        :value="modelValue.intro"
        type="text"
        maxlength="80"
        placeholder="例：小马开心挥手打招呼"
        @input="emit('update:modelValue', { ...modelValue, intro: $event.target.value })"
      />
    </label>

    <label class="fld">
      <span>详细描述 <em class="hint">（只写图片本身：画面、表情动作和氛围）</em></span>
      <textarea
        :value="modelValue.detail"
        rows="4"
        placeholder="例：画面里一只小马兴奋地挥手，眼睛睁大，嘴角上扬，整体氛围明亮活泼。"
        @input="emit('update:modelValue', { ...modelValue, detail: $event.target.value })"
      />
    </label>

    <label class="fld">
      <span>图中文字 <em class="hint">（OCR 原文，按图中实际文字保存，不改写）</em></span>
      <textarea
        :value="modelValue.image_text"
        rows="3"
        placeholder="例：你为什么这样看着我？"
        @input="emit('update:modelValue', { ...modelValue, image_text: $event.target.value })"
      />
    </label>

    <div class="fld">
      <span>用户收藏权限</span>
      <div class="chip-group">
        <button
          type="button"
          class="chip"
          :class="{ active: modelValue.allow_user_save !== false && Number(modelValue.allow_user_save ?? 1) !== 0 }"
          @click="emit('update:modelValue', { ...modelValue, allow_user_save: true })"
        >允许用户收藏</button>
        <button
          type="button"
          class="chip chip-block"
          :class="{ active: modelValue.allow_user_save === false || Number(modelValue.allow_user_save ?? 1) === 0 }"
          @click="emit('update:modelValue', { ...modelValue, allow_user_save: false })"
        >禁止收藏</button>
      </div>
    </div>

    <div class="fld">
      <span>审核状态 <em class="hint">（可用 = 启用聊天使用；草稿/停用 = 不进入聊天）</em></span>
      <div class="chip-group">
        <button
          v-for="(label, val) in REVIEW_STATUSES"
          :key="val"
          type="button"
          class="chip"
          :class="{ active: (modelValue.review_status || 'ready') === val }"
          @click="emit('update:modelValue', { ...modelValue, review_status: val })"
        >{{ label }}</button>
      </div>
    </div>

    <!-- 情绪（多选 chip） -->
    <div class="fld">
      <span>情绪</span>
      <div class="chip-group">
        <button
          v-for="(label, val) in EMOTIONS"
          :key="val"
          type="button"
          class="chip"
          :class="{ active: modelValue.emotions?.includes(val) }"
          @click="toggleArr('emotions', val)"
        >{{ label }}</button>
      </div>
    </div>

    <!-- 强度（单选） -->
    <div class="fld">
      <span>强度</span>
      <div class="chip-group">
        <button
          v-for="(label, val) in INTENSITIES"
          :key="val"
          type="button"
          class="chip"
          :class="{ active: modelValue.intensity === val }"
          @click="emit('update:modelValue', { ...modelValue, intensity: val })"
        >{{ label }}</button>
      </div>
    </div>

    <!-- 年龄分级（单选） -->
    <div class="fld">
      <span>年龄分级</span>
      <div class="chip-group">
        <button
          v-for="(label, val) in AGE_RATINGS"
          :key="val"
          type="button"
          class="chip"
          :class="['chip-age-' + val, { active: modelValue.age_rating === val }]"
          @click="emit('update:modelValue', { ...modelValue, age_rating: val })"
        >{{ label }}</button>
      </div>
    </div>

    <!-- 自定义标签 -->
    <div class="fld">
      <span>自定义标签</span>
      <div class="custom-tags-row">
        <span
          v-for="(t, i) in modelValue.custom_tags"
          :key="i"
          class="custom-tag"
          @click="removeCustomTag(i)"
          title="点击移除"
        >{{ t }} ×</span>
        <input
          v-model="customTagInput"
          type="text"
          class="custom-tag-input"
          placeholder="输入后回车添加"
          @keydown.enter.prevent="addCustomTag"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({ modelValue: { type: Object, required: true } })
const emit = defineEmits(['update:modelValue'])

const EMOTIONS = {
  // 基础情绪
  happy: '开心', excited: '兴奋', laugh: '大笑', funny: '搞笑',
  shy: '害羞', cute: '撒娇', smug: '得意', neutral: '平静',
  aggrieved: '委屈', anticipate: '期待', sad: '难过', cry: '哭泣',
  angry: '生气', surprised: '惊讶', scared: '害怕', curious: '好奇',
  disgusted: '厌恶', speechless: '无语', confused: '困惑', skeptical: '怀疑',
  embarrassed: '尴尬', nervous: '紧张', disappointed: '失望', helpless: '无奈',
  touched: '感动', apologetic: '抱歉', playful: '调皮', tired: '疲惫',
  // 伴侣向
  flirty: '撩人', love: '爱意', yearning: '思念', jealous: '吃醋',
}
const INTENSITIES = { mild: '轻度', moderate: '中等', strong: '强烈' }
const AGE_RATINGS = { all: '全年龄', teen: '青少年', adult: '成人 R18' }
const REVIEW_STATUSES = { draft: '草稿', ready: '可用', disabled: '停用' }

const customTagInput = ref('')

function toggleArr(field, val) {
  const cur = [...(props.modelValue[field] || [])]
  const idx = cur.indexOf(val)
  if (idx === -1) cur.push(val)
  else cur.splice(idx, 1)
  emit('update:modelValue', { ...props.modelValue, [field]: cur })
}

function addCustomTag() {
  const t = customTagInput.value.trim()
  if (!t) return
  const cur = [...(props.modelValue.custom_tags || [])]
  if (!cur.includes(t)) cur.push(t)
  emit('update:modelValue', { ...props.modelValue, custom_tags: cur })
  customTagInput.value = ''
}

function removeCustomTag(i) {
  const cur = [...(props.modelValue.custom_tags || [])]
  cur.splice(i, 1)
  emit('update:modelValue', { ...props.modelValue, custom_tags: cur })
}
</script>

<style scoped>
.tag-form { display: flex; flex-direction: column; }

.fld {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}
.fld span { color: #cbd5e1; font-weight: 500; }
.hint { font-size: 0.75rem; font-weight: 400; color: #64748b; }

.fld input,
.fld textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 0.55rem 0.75rem !important;
}
.fld textarea {
  resize: vertical;
  min-height: 4.8rem;
}

/* ── Chip 多选 ── */
.chip-group {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}
.chip {
  padding: 0.2rem 0.55rem;
  border-radius: 99px;
  border: 1px solid rgba(148,163,184,0.25);
  background: transparent;
  color: #94a3b8;
  font-size: 0.78rem;
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.chip:hover { border-color: rgba(148,163,184,0.5); color: #e2e8f0; }
.chip.active {
  background: rgba(139,92,246,0.2);
  border-color: rgba(139,92,246,0.55);
  color: #c4b5fd;
}
.chip-age-teen.active { background: rgba(245,158,11,0.18); border-color: rgba(245,158,11,0.5); color: #fbbf24; }
.chip-age-adult.active { background: rgba(239,68,68,0.18); border-color: rgba(239,68,68,0.5); color: #f87171; }
.chip-block.active { background: rgba(239,68,68,0.16); border-color: rgba(239,68,68,0.48); color: #fca5a5; }

/* ── 自定义标签 ── */
.custom-tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  align-items: center;
}
.custom-tag {
  font-size: 0.75rem;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  background: rgba(100,116,139,0.2);
  color: #94a3b8;
  cursor: pointer;
  transition: background 0.12s;
}
.custom-tag:hover { background: rgba(239,68,68,0.2); color: #f87171; }
.custom-tag-input {
  border: none;
  background: transparent;
  color: #cbd5e1;
  font-size: 0.82rem;
  outline: none;
  width: 120px;
  padding: 0.15rem 0.25rem;
  border-bottom: 1px solid rgba(148,163,184,0.25);
}
</style>
