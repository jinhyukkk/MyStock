from fastapi import FastAPI
from app.api import router

app = FastAPI(title="MyStock")
app.include_router(router)
