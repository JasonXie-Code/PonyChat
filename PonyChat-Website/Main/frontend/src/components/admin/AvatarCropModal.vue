<template>
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="crop-mask admin-shell"
      role="dialog"
      aria-modal="true"
      @click.self="onClose"
    >
      <div class="crop-card card">
        <header class="crop-h">
          <h3 class="crop-title">裁剪头像</h3>
          <p class="crop-sub">1:1 比例 · 拖动调整位置，滚轮/双指缩放</p>
        </header>
        <div v-if="error" class="crop-err">{{ error }}</div>
        <div v-else class="crop-body">
          <div ref="boxRef" class="crop-square" @wheel.prevent="onWheel">
            <canvas
              ref="cvRef"
              class="crop-cv"
              @pointerdown="onPointerDown"
              @pointermove="onPointerMove"
              @pointerup="onPointerUp"
              @pointercancel="onPointerUp"
            />
          </div>
        </div>
        <footer class="crop-foot">
          <span class="crop-zoom-hint" v-if="!error">缩放 {{ zoom.toFixed(2) }}×</span>
          <div class="crop-actions">
            <button type="button" class="btn" :disabled="loading" @click="onClose">取消</button>
            <button type="button" class="btn btn-primary" :disabled="loading || !img" @click="onConfirm">
              {{ loading ? '处理中…' : '确定' }}
            </button>
          </div>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, watch, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 待裁切的本地图片文件 */
  file: { type: Object, default: null, validator: (v) => v == null || v instanceof File },
})

const emit = defineEmits(['update:modelValue', 'confirm', 'close'])

const error = ref('')
const loading = ref(false)
const img = ref(null)
const imgObjectUrl = ref('')

const boxRef = ref(null)
const cvRef = ref(null)

const nw = ref(0)
const nh = ref(0)
/** 与 App 内 AvatarCropDialog 一致：1～3 倍「放大取景」 */
const zoom = ref(1)
const offX = ref(0)
const offY = ref(0)

let dragPointerId = null
let lastX = 0
let lastY = 0

const pointers = new Map()
let pinchStartDist = 0
let pinchStartZoom = 1

const OUT = 512

let ro = null
/** 避免「打开弹层时 modelValue 与 file 各触发一次 init」导致 revoke 后第一张图 onerror */
let loadToken = 0

watch(
  () => [props.modelValue, props.file],
  () => {
    if (props.modelValue && props.file) {
      nextTick(() => {
        if (props.modelValue && props.file) initFromFile()
      })
    } else if (!props.modelValue) {
      resetState()
    }
  },
  { flush: 'post' },
)

watch([() => props.modelValue, zoom, offX, offY, () => img.value], () => {
  if (props.modelValue && img.value) {
    nextTick(() => draw())
  }
})

onUnmounted(() => {
  if (ro) {
    ro.disconnect()
    ro = null
  }
  revokeObj()
})

function revokeObj() {
  const u = imgObjectUrl.value
  if (u && u.startsWith('blob:')) {
    try {
      URL.revokeObjectURL(u)
    } catch {
      /* 忽略 */
    }
  }
  imgObjectUrl.value = ''
}

function onClose() {
  emit('update:modelValue', false)
  emit('close')
  resetState()
}

function resetState() {
  if (ro) {
    ro.disconnect()
    ro = null
  }
  revokeObj()
  img.value = null
  error.value = ''
  loading.value = false
  nw.value = 0
  nh.value = 0
  zoom.value = 1
  offX.value = 0
  offY.value = 0
  dragPointerId = null
  pointers.clear()
  pinchStartDist = 0
}

function initFromFile() {
  if (!props.file) {
    error.value = '未选择图片'
    return
  }
  const myToken = ++loadToken
  error.value = ''
  revokeObj()
  pointers.clear()
  dragPointerId = null

  const file = props.file
  const url = URL.createObjectURL(file)
  imgObjectUrl.value = url

  const tryAssignImage = (image) => {
    if (myToken !== loadToken) return
    nw.value = image.naturalWidth
    nh.value = image.naturalHeight
    if (nw.value < 32 || nh.value < 32) {
      error.value = '图片尺寸过小'
      img.value = null
      return
    }
    img.value = image
    zoom.value = 1
    offX.value = 0
    offY.value = 0
    nextTick(() => {
      if (myToken !== loadToken) return
      if (boxRef.value) {
        if (ro) {
          ro.disconnect()
          ro = null
        }
        ro = new ResizeObserver(() => {
          if (props.modelValue && img.value) nextTick(() => draw())
        })
        ro.observe(boxRef.value)
      }
      draw()
    })
  }

  const image = new Image()
  // blob:/data: 本地同源，勿设 crossOrigin，否则易触发加载失败
  image.decoding = 'async'
  image.onload = () => {
    if (myToken !== loadToken) return
    tryAssignImage(image)
  }
  image.onerror = () => {
    if (myToken !== loadToken) return
    revokeObj()
    const fr = new FileReader()
    fr.onload = () => {
      if (myToken !== loadToken) return
      const r = fr.result
      if (typeof r !== 'string') {
        error.value = '无法读取图片文件'
        return
      }
      const im2 = new Image()
      im2.onload = () => {
        if (myToken !== loadToken) return
        imgObjectUrl.value = r
        tryAssignImage(im2)
      }
      im2.onerror = () => {
        if (myToken !== loadToken) return
        const t = (file.type || '').toLowerCase()
        if (t.includes('heic') || t.includes('heif') || /\.hei[cf]$/i.test(file.name)) {
          error.value = '当前浏览器无法解码 HEIC/HEIF，请换用 JPG 或 PNG'
        } else {
          error.value = '无法加载图片，请使用 JPG、PNG 或 WebP'
        }
        img.value = null
      }
      im2.src = r
    }
    fr.onerror = () => {
      if (myToken !== loadToken) return
      error.value = '无法读取图片文件'
    }
    fr.readAsDataURL(file)
  }
  image.src = url
}

function getCropSourceRect() {
  const w = nw.value
  const h = nh.value
  const z = Math.max(1, Math.min(3, zoom.value))
  const cropSize = Math.max(64, Math.min(w, h) / z)
  const maxL = Math.max(0, w - cropSize)
  const maxT = Math.max(0, h - cropSize)
  const halfL = maxL / 2
  const halfT = maxT / 2
  const left = maxL > 0 ? Math.round(halfL + offX.value * halfL) : 0
  const top = maxT > 0 ? Math.round(halfT + offY.value * halfT) : 0
  return { left, top, size: Math.round(cropSize) }
}

function displaySide() {
  const box = boxRef.value
  if (!box) return 300
  const w = box.clientWidth
  return w > 0 ? Math.floor(w) : 300
}

function dist(a, b) {
  const dx = a.x - b.x
  const dy = a.y - b.y
  return Math.hypot(dx, dy)
}

function draw() {
  const el = cvRef.value
  const im = img.value
  if (!el || !im) return
  const dpr = Math.min(2, window.devicePixelRatio || 1)
  const display = displaySide()
  const px = Math.max(1, Math.round(display * dpr))
  el.width = px
  el.height = px
  el.style.width = `${display}px`
  el.style.height = `${display}px`
  const ctx = el.getContext('2d')
  if (!ctx) return
  const { left, top, size } = getCropSourceRect()
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, px, px)
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(im, left, top, size, size, 0, 0, px, px)
}

function onPointerDown(e) {
  if (!img.value) return
  e.currentTarget.setPointerCapture(e.pointerId)
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  if (pointers.size === 1) {
    dragPointerId = e.pointerId
    lastX = e.clientX
    lastY = e.clientY
  }
  if (pointers.size === 2) {
    const [a, b] = Array.from(pointers.values())
    pinchStartDist = dist(a, b)
    pinchStartZoom = zoom.value
  }
}

function onPointerMove(e) {
  if (!img.value) return
  if (pointers.has(e.pointerId)) {
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  }
  if (pointers.size === 2) {
    const [a, b] = Array.from(pointers.values())
    const dnow = dist(a, b)
    if (pinchStartDist > 1 && dnow > 1) {
      const ratio = dnow / pinchStartDist
      zoom.value = Math.max(1, Math.min(3, pinchStartZoom * ratio))
    }
    return
  }
  if (dragPointerId !== e.pointerId) return
  const box = boxRef.value
  if (!box) return
  const bw = box.clientWidth
  if (bw < 1) return
  const dx = e.clientX - lastX
  const dy = e.clientY - lastY
  lastX = e.clientX
  lastY = e.clientY
  const d = 2 / bw
  offX.value = Math.max(-1, Math.min(1, offX.value - dx * d * 1.25))
  offY.value = Math.max(-1, Math.min(1, offY.value - dy * d * 1.25))
}

function onPointerUp(e) {
  if (pointers.has(e.pointerId)) {
    pointers.delete(e.pointerId)
  }
  if (e.pointerId === dragPointerId) {
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* 忽略 */
    }
    dragPointerId = null
  }
  if (pointers.size === 0) {
    pinchStartDist = 0
  } else if (pointers.size === 1) {
    const p = Array.from(pointers.values())[0]
    dragPointerId = Array.from(pointers.keys())[0]
    lastX = p.x
    lastY = p.y
  }
}

function onWheel(e) {
  if (!img.value) return
  const delta = e.deltaY
  const factor = delta > 0 ? 0.95 : 1.05
  zoom.value = Math.max(1, Math.min(3, zoom.value * factor))
}

function onConfirm() {
  const im = img.value
  if (!im) return
  loading.value = true
  error.value = ''
  const { left, top, size } = getCropSourceRect()
  const c = document.createElement('canvas')
  c.width = OUT
  c.height = OUT
  const ctx = c.getContext('2d')
  if (!ctx) {
    error.value = '无法创建画布'
    loading.value = false
    return
  }
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, OUT, OUT)
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(im, left, top, size, size, 0, 0, OUT, OUT)
  c.toBlob(
    (blob) => {
      loading.value = false
      if (!blob) {
        error.value = '导出失败'
        return
      }
      const name =
        props.file && props.file.name ? String(props.file.name).replace(/\.[^.]+$/, '') : 'avatar'
      const outFile = new File([blob], `${name || 'avatar'}.jpg`, { type: 'image/jpeg' })
      emit('confirm', outFile)
      emit('update:modelValue', false)
      resetState()
    },
    'image/jpeg',
    0.9,
  )
}
</script>

<style scoped>
.crop-mask {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(15, 23, 42, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.crop-card {
  width: min(400px, 100%);
  max-height: 90dvh;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}
.crop-h {
  padding: 1rem 1.25rem 0.5rem;
  border-bottom: 1px solid var(--stroke, rgba(148, 163, 184, 0.15));
  flex-shrink: 0;
}
.crop-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}
.crop-sub {
  margin: 0.4rem 0 0;
  font-size: 0.75rem;
  color: var(--text-muted, #94a3b8);
}
.crop-err {
  color: #f0a0a0;
  padding: 0.75rem 1.25rem;
  font-size: 0.85rem;
}
.crop-body {
  padding: 1rem 1.25rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  min-height: 0;
}
.crop-square {
  position: relative;
  width: 320px;
  max-width: 100%;
  aspect-ratio: 1;
  background: #0f172a;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--stroke, rgba(148, 163, 184, 0.2));
  touch-action: none;
}
.crop-cv {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  cursor: grab;
  touch-action: none;
}
.crop-cv:active {
  cursor: grabbing;
}
.crop-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem 1rem;
  border-top: 1px solid var(--stroke, rgba(148, 163, 184, 0.15));
  flex-shrink: 0;
}
.crop-zoom-hint {
  font-size: 0.75rem;
  color: var(--text-muted, #94a3b8);
}
.crop-actions {
  display: flex;
  gap: 0.5rem;
  margin-left: auto;
}
</style>
