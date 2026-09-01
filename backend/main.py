from fastapi import FastAPI

app = FastAPI(title="project3-agent")


@app.get("/health")
def health():
    return {"status": "ok"}
