<template>
  <iframe
    :src="src"
    :title="title"
    class="legacy-frame"
    referrerpolicy="same-origin"
  />
</template>

<script setup>
defineProps({
  src: { type: String, required: true },
  title: { type: String, default: 'PonyChat' },
})
</script>

<style scoped>
.legacy-frame {
  width: 100%;
  height: 100vh;
  min-height: 100dvh;
  border: 0;
  display: block;
  background: #0f172a;
}
</style>
