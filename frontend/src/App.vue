<script setup lang="ts">
import { ref } from "vue";
import ChatView from "./views/ChatView.vue";
import TracePanel from "./components/TracePanel.vue";
import type { TraceStep } from "./types";

const steps = ref<TraceStep[]>([]);
</script>

<template>
  <div class="layout">
    <ChatView :steps="steps" class="left" />
    <TracePanel :steps="steps" class="right" />
  </div>
</template>

<style>
.layout {
  display: grid;
  grid-template-columns: 5fr 7fr;
  height: 100vh;
  gap: 12px;
  box-sizing: border-box;
  padding: 12px;
}
.left {
  border-right: 1px solid #e5e7eb;
  overflow: hidden;
}
.right {
  overflow-y: auto;
}
</style>
