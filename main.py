from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from database.connection import Settings
from routes.users import user_router
from routes.reactions import reactions_router

import uvicorn

app = FastAPI()

settings = Settings()

# Register routes

app.include_router(user_router,  prefix="/user")
app.include_router(reactions_router, prefix="/reaction")




@app.on_event("startup")
async def init_db():
    await settings.initialize_database()

@app.get("/")
async def home():
    return RedirectResponse(url="/reaction/")


if __name__ == '__main__':
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
