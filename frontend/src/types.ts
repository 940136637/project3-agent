export interface TraceStep {
    id: number;
    type: "thinking" | "tool";
    status: "running" | "done" | "error";
    title: string;        // 思考 / 工具名
    detail: string;       // thinking 累积文本 / 工具返回内容
    args?: string;        // tool_call 参数（JSON 字符串）
    ok?: boolean;         // tool_result.ok
    chartOption?: object; // chart 事件的 option
  }