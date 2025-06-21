from fastapi import FastAPI
from utils.logger_factory import new_logger

app = FastAPI()

@app.get("/api/hello")
def hello():
    log = new_logger("hello")
    log.info("endpoint invoked")
    return {"message": "Hello from /api/hello!"}
