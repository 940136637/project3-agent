import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.trace import stream_trace

app = FastAPI(title="project3-agent")


@app.get("/health")
def health():
    return {"status": "ok"}


class ChatStreamRequest(BaseModel):
    question: str


@app.post("/api/chat/stream")
async def chat_stream(req: ChatStreamRequest):
    async def gen():
        try:
            async for ev_name, data in stream_trace(req.question):
                yield f"event: {ev_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'detail': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
