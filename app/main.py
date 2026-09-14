from fastapi import FastAPI

from app.api.calls import router as calls_router

app = FastAPI(title="Vinmec Callbot")
app.include_router(calls_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
