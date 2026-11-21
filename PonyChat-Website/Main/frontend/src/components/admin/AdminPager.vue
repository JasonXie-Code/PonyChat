<template>
  <div v-if="total > pageSize" class="admin-pager">
    <span class="muted">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 条</span>
    <div class="pager-btns">
      <button type="button" class="btn" :disabled="page <= 1" @click="$emit('prev')">上一页</button>
      <button type="button" class="btn" :disabled="page >= totalPages" @click="$emit('next')">下一页</button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  page: { type: Number, required: true },
  totalPages: { type: Number, required: true },
  total: { type: Number, required: true },
  pageSize: { type: Number, required: true },
})
defineEmits(['prev', 'next'])
</script>

<style scoped>
.admin-pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  flex-shrink: 0;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--stroke, rgba(148, 163, 184, 0.15));
}
.pager-btns {
  display: flex;
  gap: 0.35rem;
}
</style>
