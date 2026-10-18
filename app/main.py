import asyncio

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

SSE_TEST_INTERVAL = 1.0


@app.get("/api/health")
def health():
    return {"ok": True}


# 임시: 배포 SSE 확인용. 작업 6에서 삭제
@app.get("/api/sse-test")
async def sse_test():
    async def events():
        for n in range(1, 4):
            yield f"data: {n}\n\n"
            await asyncio.sleep(SSE_TEST_INTERVAL)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
