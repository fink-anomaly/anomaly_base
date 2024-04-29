from typing import Dict, List, Optional

from database.connection import Settings
from routes.users import user_router
from routes.reactions import reactions_router
from routes.reactions import reactions
from fastapi import Depends, FastAPI, HTTPException, Response, status, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from auth.hash_password import HashPassword
from models.base_types import User
from auth.jwt_handler import create_access_token
from auth.jwt_handler import get_current_user_from_cookie, get_current_user_from_token
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
import aiohttp


class Update(BaseModel):
    update_id: int
    message: dict

import uvicorn

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
settings = Settings()
hash_password = HashPassword()

# Register routes

app.include_router(user_router,  prefix="/user")
app.include_router(reactions_router, prefix="/reaction")


# async def get_bot_updates():
#     url = f'https://api.telegram.org/bot{settings.TG_TOKEN}/getUpdates'
#     async with aiohttp.ClientSession() as session:
#         async with session.get(url) as response:
#             updates = await response.json()
#             return updates["result"] if 'result' in updates else None

async def get_reactions_table(name) -> str:
   rows = await reactions.find_with_user(name)
   rows = await rows.to_list()
   rows = [dict(obj) for obj in rows]
   return rows

@app.on_event("startup")
async def init_db():
    await settings.initialize_database()
    #bot_info = await get_bot_updates()
    #print(bot_info)

@app.get("/all_reactions")
async def all_reactions():
    return RedirectResponse(url="/reaction/")


@app.post("token")
async def login_for_access_token(
        response: Response,
        form_data: OAuth2PasswordRequestForm = Depends()
) -> Dict[str, str]:
    user = await User.find_one(User.name == form_data.username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    if hash_password.verify_hash(form_data.password, user.password):
        access_token = create_access_token(user.name)
        response.set_cookie(
            key="access_token",
            value=f"Bearer {access_token}",
            httponly=True
        )
        return {"access_token": access_token, "token_type": "bearer"}
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")



@app.get("/auth/login", response_class=HTMLResponse)
async def login_get(request: Request):
    context = {
        "request": request,
    }
    return templates.TemplateResponse("index.html", context)


class LoginForm:
    def __init__(self, request: Request):
        self.request: Request = request
        self.errors: List = []
        self.username: Optional[str] = None
        self.password: Optional[str] = None

    async def load_data(self):
        form = await self.request.form()
        self.username = form.get("username")
        self.password = form.get("password")

    async def is_valid(self):
        if not self.username:
            self.errors.append("Login is required")
        if not self.password:
            self.errors.append("A valid password is required")
        if not self.errors:
            return True
        return False




@app.post("/auth/login", response_class=HTMLResponse)
async def login_post(request: Request):
    form = LoginForm(request)
    await form.load_data()
    if await form.is_valid():
        try:
            response = RedirectResponse("/", status.HTTP_302_FOUND)
            await login_for_access_token(response=response, form_data=form)
            form.__dict__.update(msg="Login Successful!")
            print("[green]Login successful!!!!")
            return response
        except HTTPException:
            form.__dict__.update(msg="")
            form.__dict__.get("errors").append("Incorrect Login or Password")
            return templates.TemplateResponse("index.html", form.__dict__)
    return templates.TemplateResponse("index.html", form.__dict__)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        user = await get_current_user_from_cookie(request)
        data = await get_reactions_table(user.name)
    except:
        user = None
        data = None
    context = {
        "user": user,
        "request": request,
        "table": data,
        "token": request.cookies.get('access_token') if not user is None else '',
        "count": len(data) if not data is None else 0
    }
    return templates.TemplateResponse("index.html", context)




if __name__ == '__main__':
    #uvicorn.run("main:app", host="0.0.0.0", port=24000, reload=True)
    uvicorn.run("main:app", host="127.0.0.1", port=24000, reload=True)
