from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from database.connection import conn

from routes.users import user_router
from routes.reactions import reactions_router

import uvicorn

app = FastAPI()

# Register routes

app.include_router(user_router,  prefix="/user")
app.include_router(reactions_router, prefix="/reaction")




@app.on_event("startup")
def on_startup():
    conn()

@app.get("/")
async def home():
    return RedirectResponse(url="/reaction/")

if __name__ == '__main__':
    uvicorn.run("main:app", host="127.0.0.1", port=80, reload=True)