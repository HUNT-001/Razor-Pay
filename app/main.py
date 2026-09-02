from fastapi import FastAPI
from app.db import Base, engine
from app.routes import webhooks, analytics, cases, dashboard
from app import models  # ensure model registration

Base.metadata.create_all(bind=engine)

app = FastAPI(title="RecoverAI", version="0.1.0")
app.include_router(webhooks.router)
app.include_router(analytics.router)
app.include_router(cases.router)
app.include_router(dashboard.router)


@app.get("/")
def root():
    return {"service": "RecoverAI", "status": "ok"}
