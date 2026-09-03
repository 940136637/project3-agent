<template>
  <div class="chat-view">
    <div class="chat-header">
      <button @click="handleNewChat">新对话</button>
    </div>

    <div class="message-list">
      <div
        v-for="msg in messages"
        :key="msg.id"
        :class="['message-item', msg.role]"
      >
        <div class="message-card">{{ msg.content }}</div>
      </div>
    </div>

    <div class="chat-input-area">
      <textarea
        v-model="input"
        :disabled="loading"
        @keydown.enter="onEnter"
        placeholder="请输入问题..."
        rows="3"
      ></textarea>
      <button @click="send" :disabled="loading">
        {{ loading ? "请求中…" : "发送" }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { streamChat } from "../api/index";
import type { TraceStep } from "../types";

const props = defineProps<{
  steps: TraceStep[];
}>();

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
}

const messages = ref<ChatMessage[]>([]);
const input = ref("");
const loading = ref(false);
let msgIdCounter = 0;

function handleEvent(name: string, data: any) {
  switch (name) {
    case "answer":
      messages.value.push({
        id: msgIdCounter++,
        role: "assistant",
        content: data.text,
      });
      break;
    case "error":
      messages.value.push({
        id: msgIdCounter++,
        role: "assistant",
        content: data.detail,
      });
      const step = props.steps[props.steps.length - 1];
      if (step) {
        step.status = "error";
      }
      break;
    // Task 6: 事件驱动 steps
    // step_start / thinking / tool_call / tool_result / chart / step_start / step_end 在此处理更新props.steps
    case "step_start": {
      props.steps.push({
        id: data.step_idx,
        type: data.type,
        status: "running",
        title: data.type === "thinking" ? "思考中" : "",
        detail: "",
        args: undefined,
        ok: undefined,
        chartOption: undefined,
      });
      break;
    }
    case "thinking": {
      const step = props.steps[props.steps.length - 1];
      if (step) {
        step.detail += data.text;
      }
      break;
    }
    case "tool_call": {
      const step = props.steps[props.steps.length - 1];
      if (step) {
        step.title = data.tool_name;
        step.args = JSON.stringify(data.args, null, 2);
      }
      break;
    }
    case "tool_result": {
      const step = props.steps[props.steps.length - 1];
      if (step) {
        step.detail = data.result;
        step.ok = data.ok;
        step.status = data.ok ? "done" : "error"
      }
      break;
    }
    case "chart": {
      const step = props.steps[props.steps.length - 1];
      if (step) {
        step.chartOption = data.option;
      }
      break;
    }
    case "step_end": {
      const step = props.steps.find(s => s.id === data.step_idx);
      if (step && step.status !== "error") {
           step.status = "done"
      }
  }
}
}

function onDone() {
  loading.value = false;
}

function onError(msg: string) {
  loading.value = false;
  messages.value.push({
    id: msgIdCounter++,
    role: "assistant",
    content: msg,
  });
}

async function send() {
  const q = input.value.trim();
  if (!q || loading.value) return;

  // 推送用户消息
  messages.value.push({
    id: msgIdCounter++,
    role: "user",
    content: q,
  });

  input.value = "";
  loading.value = true;

  await streamChat(q, handleEvent, onDone, onError);
}

function handleNewChat() {
  messages.value = [];
  // props数组共享引用，splice原地清空
  props.steps.splice(0, props.steps.length);
}

function onEnter(e: KeyboardEvent) {
    if (e.isComposing || e.shiftKey) return; // 输入法确认 / Shift+Enter 换行 → 放行
    e.preventDefault();                      // 拦住 textarea 默认的插换行
    send();
  }
</script>

<style scoped>
.chat-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 12px;
  box-sizing: border-box;
}
.chat-header {
  margin-bottom: 12px;
}
.message-list {
  flex: 1;
  overflow-y: auto;
  margin-bottom: 12px;
}
.message-item {
  margin: 8px 0;
}
.message-item.user {
  text-align: right;
}
.message-item.assistant {
  text-align: left;
}
.message-card {
  display: inline-block;
  max-width: 70%;
  padding: 10px 14px;
  border-radius: 8px;
  white-space: pre-wrap;
}
.user .message-card {
  background: #409eff;
  color: white;
}
.assistant .message-card {
  background: #f2f3f5;
  color: #333;
}
.chat-input-area {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
textarea {
  flex: 1;
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 6px;
}
button {
  padding: 8px 16px;
}
</style>