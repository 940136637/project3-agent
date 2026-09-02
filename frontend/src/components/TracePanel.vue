<script setup lang="ts">
import type { TraceStep } from "../types";

defineProps<{
  steps: TraceStep[];
}>();
</script>

<template>
  <div class="trace-panel">
    <h2>Agent 执行链路</h2>
    <!-- Task 6: 时间线渲染 -->
  </div>
</template>

<style scoped>
.trace-panel {
  padding: 8px;
}
</style>