<!-- frontend/src/components/TracePanel.vue -->
<script setup lang="ts">
import { onBeforeUnmount } from "vue";
import * as echarts from "echarts";
import type { TraceStep } from "../types";

defineProps<{
  steps: TraceStep[];
}>();

// step.id → echarts实例映射
const charts = new Map<number, echarts.ECharts>();
// 保存resize观察器，卸载时清理
const observers = new Map<number, ResizeObserver>();

function initChart(el: unknown, step: TraceStep) {
  // el为null代表DOM卸载；已经初始化过直接跳过，防止重复init
  if (!el || charts.has(step.id)) return;

  const dom = el as HTMLDivElement;
  const chartIns = echarts.init(dom);
chartIns.setOption(step.chartOption as echarts.EChartsOption);
  charts.set(step.id, chartIns);

  // 容器尺寸自适应
  const ro = new ResizeObserver(() => {
    chartIns.resize();
  });
  ro.observe(dom);
  observers.set(step.id, ro);
}

// 组件卸载：销毁echarts实例 + 断开ResizeObserver，防止内存泄漏
onBeforeUnmount(() => {
  charts.forEach((ins) => ins.dispose());
  charts.clear();
  observers.forEach((ro) => ro.disconnect());
  observers.clear();
});
</script>

<template>
  <div class="trace-panel">
    <h2>Agent 执行链路</h2>
    <div class="timeline">
      <div
        v-for="step in steps"
        :key="step.id"
        class="step-card"
        :class="[step.status, step.type]"
      >
        <!-- 左侧圆点徽章 -->
        <div class="badge">
          <span v-if="step.type === 'thinking' && step.status === 'running'" class="dot-thinking"><i></i><i></i><i></i></span>
          <span v-else-if="step.type === 'tool' && step.status === 'running'" class="dot-tool"></span>
          <span v-else class="dot-static"></span>
        </div>

        <!-- 标题区域 -->
        <div class="step-content">
          <div class="step-title">{{ step.title }}</div>

          <!-- thinking类型：思考文本块 -->
          <div v-if="step.type === 'thinking' && step.detail" class="think-block">
            {{ step.detail }}
          </div>

          <!-- tool类型：参数 / 返回结果折叠面板 -->
          <div v-if="step.type === 'tool'" class="tool-block">
            <details open class="details-item">
              <summary>调用参数</summary>
              <pre class="pre-code">{{ step.args }}</pre>
            </details>
            <details class="details-item">
              <summary>返回内容</summary>
              <pre class="pre-code">{{ step.detail }}</pre>
            </details>
          </div>

          <!-- 图表容器，chartOption存在才创建DOM -->
          <div
            v-if="step.chartOption"
            class="chart-box"
            :ref="el => initChart(el, step)"
          ></div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trace-panel {
  height: 100%;
  overflow-y: auto;
  padding: 12px;
}
.trace-panel h2 {
  margin-top: 0;
  font-size: 18px;
}

/* 时间线竖线 */
.timeline {
  position: relative;
  padding-left: 28px;
}
.timeline::before {
  content: "";
  position: absolute;
  left: 9px;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #e2e8f0;
}

.step-card {
  position: relative;
  margin: 16px 0;
  display: flex;
  gap: 12px;
}

/* 圆点徽章容器 */
.badge {
  position: absolute;
  left: -28px;
  top: 4px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 静态圆点 */
.dot-static {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #94a3b8;
}
/* thinking呼吸三点动画 */
.dot-thinking {
  display: flex;
  gap: 3px;
}
.dot-thinking i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background-color: #3b82f6;
  animation: breath 1.4s infinite ease-in-out;
}
.dot-thinking i:nth-child(1) {
  animation-delay: 0s;
}
.dot-thinking i:nth-child(2) {
  animation-delay: 0.4s;
}
.dot-thinking i:nth-child(3) {
  animation-delay: 0.8s;
}

/* tool转圈loading */
.dot-tool {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid #bfdbfe;
  border-top-color: #3b82f6;
  animation: spin 1s linear infinite;
}

/* 状态色：running蓝 / done绿 / error红 */
.step-card.running .dot-static { background: #3b82f6; }
.step-card.done .dot-static { background: #10b981; }
.step-card.error .dot-static { background: #ef4444; }

.step-content {
  flex: 1;
}
.step-title {
  font-weight: 600;
  margin-bottom: 6px;
}
.step-card.running .step-title { color: #2563eb; }
.step-card.done .step-title { color: #059669; }
.step-card.error .step-title { color: #dc2626; }

.think-block {
  background: #f8fafc;
  padding: 8px 10px;
  border-radius: 6px;
  white-space: pre-wrap;
  font-size: 13px;
}

.tool-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.details-item {
  background: #f8fafc;
  border-radius: 6px;
  padding: 6px 8px;
}
.pre-code {
  margin: 6px 0 0;
  font-size: 12px;
  white-space: pre-wrap;
  overflow-x: auto;
}

/* echarts容器必须定高度 */
.chart-box {
  margin-top: 10px;
  height: 260px;
  width: 100%;
}

@keyframes breath {
  0%,100% { opacity: 0.2; }
  50% { opacity: 1; }
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
