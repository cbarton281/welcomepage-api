from fastapi import FastAPI

app = FastAPI()

@app.get("/api/hello")
def hello():
    log = new_logger("hello")
    log.info("endpoint invoked")
    return {"message": "Hello from /api/hello!"}
