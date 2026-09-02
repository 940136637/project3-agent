export async function streamChat(
  question: string,
  onEvent: (name: string, data: any) => void,
  onDone: () => void,
  onError: (msg: string) => void,
): Promise<void> {
  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ question }),
    });

    if (!res.ok) {
      onError(`HTTP错误：${res.status}`);
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) {
      onError("当前环境不支持 ReadableStream");
      return;
    }

    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      // 流式解码，追加到缓冲区
      buffer += decoder.decode(value, { stream: true });

      // 按SSE分隔符切分完整消息
      const frames = buffer.split("\n\n");
      // 剩余不完整片段留在buffer，下一轮继续拼接
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        if (!frame.trim()) continue;

        let eventName = "";
        let dataStr = "";
        const lines = frame.split("\n");
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventName = line.slice("event: ".length);
          } else if (line.startsWith("data: ")) {
            dataStr = line.slice("data: ".length);
          }
        }

        if (!eventName || !dataStr) continue;

        try {
          const payload = JSON.parse(dataStr);
          onEvent(eventName, payload);
        } catch (parseErr) {
          console.warn("SSE帧JSON解析失败", parseErr);
        }
      }
    }
    // 流读取完毕触发完成回调
    onDone();
  } catch (err) {
    const message = err instanceof Error ? err.message : "网络请求异常";
    onError(message);
  }
}