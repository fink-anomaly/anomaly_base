from typing import Dict, List, Optional
import markdown
import datetime
import sys
import os
from database.mongo import Settings
from routes.users import user_router
import requests
from routes.reactions import reactions_router
from routes.reactions import reactions
from fastapi import Depends, FastAPI, HTTPException, Response, status, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from auth.hash_password import HashPassword
import aiohttp
from loguru import logger
from models.base_types import User
from auth.jwt_handler import create_access_token
from auth.jwt_handler import get_current_user_from_cookie, get_current_user_from_token
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from routes.upload import images
from routes.upload import image_router
from routes.users import get_postfix_by_tgid
from routes.users import config
from models.base_types import reaction
import uvicorn
import telebot

class Update(BaseModel):
    update_id: int
    message: dict



logger.remove()
logger.add(sys.stdout, enqueue=True)
bot = telebot.TeleBot(config['NOTIF']['master_pass'])
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
settings = Settings()
hash_password = HashPassword()


app.include_router(user_router,  prefix="/user")
app.include_router(reactions_router, prefix="/reaction")
app.include_router(image_router, prefix='/images')



class CallbackQuery(BaseModel):
    id: str
    from_user: dict
    message: dict
    data: str


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    update = await request.json()
    if "callback_query" in update:
        data = {
            'id': update["callback_query"]['id'],
            'from_user': update["callback_query"]['from'],
            'message': update["callback_query"]['message'],
            'data': update["callback_query"]['data']
        }
        callback_query = CallbackQuery(**data)
        await handle_callback_query(callback_query)
    else:
        if request.headers.get("content-type") == "application/json":
            json_str = await request.json()
            update = telebot.types.Update.de_json(json_str)
            bot.process_new_updates([update])
        else:
            raise HTTPException(status_code=400, detail="Invalid request")
    return {"status": "ok"}


async def handle_callback_query(callback_query: CallbackQuery):
    callback_data = callback_query.data
    is_anomaly = False if 'NA' in callback_data else True
    _, ztf_id = callback_data.split('_')

    username = await get_postfix_by_tgid(
        callback_query.from_user['id']
    )

    data = {
        'ztf_id': ztf_id,
        'tag': 'ANOMALY' if is_anomaly else 'NOT ANOMALY',
        'user': username,
        'changed_at': str(datetime.datetime.now())
    }

    new_reaction = reaction.parse_obj(data)

    event = await reactions.find_with_ztfid(new_reaction.ztf_id)
    if event:
        await event.update({"$set": {'tag': new_reaction.tag}})
    else:
        await reactions.save(new_reaction)

    url = f"https://api.telegram.org/bot{config['NOTIF']['master_pass']}/answerCallbackQuery"
    url_button_change = f"https://api.telegram.org/bot{config['NOTIF']['master_pass']}/editMessageReplyMarkup"

    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "Anomaly" if not is_anomaly else 'SET', "callback_data": f"A_{ztf_id}"},
                {"text": "Not anomaly" if is_anomaly else 'SET', "callback_data": f"NA_{ztf_id}"}
            ]
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
                url,
                data={
                    "callback_query_id": callback_query.id,
                    'text': f'The{" " if is_anomaly else " NOT "}ANOMALY mark is set for the object {ztf_id}'
                }
        ) as response:
            answer = await response.json()
            logger.info(answer)

    async with aiohttp.ClientSession() as session:
        async with session.post(
                url_button_change,
                json={
                    "chat_id": callback_query.message['chat']['id'],
                    "message_id": callback_query.message['message_id'],
                    "reply_markup": inline_keyboard
                }
        ) as response:
            answer = await response.json()
            logger.info(answer)


async def get_reactions_table(name) -> str:
   rows = await reactions.find_with_user(name)
   rows = await rows.to_list()
   rows = [dict(obj) for obj in rows]
   return rows

@app.on_event("startup")
async def init_db():
    await settings.initialize_database()

    url = f"https://api.telegram.org/bot{config['NOTIF']['master_pass']}/setWebhook"
    webhook_url = "https://anomaly.fink-broker.org/telegram-webhook"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data={"url": webhook_url}) as response:
            res = await response.json()
            print(res)

    #bot.set_webhook(webhook_url)

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


class attr_carrier:
    def __init__(self):
        pass

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        user = await get_current_user_from_cookie(request)
        data = await get_reactions_table(user.name)
        tiles = await (await images.find_with_user(user.name)).to_list()
        im_ids = []
        for obj in tiles:
            buf = attr_carrier()
            buf.cutout = f"static/{obj.id}_cutout.png"
            buf.curve = f"static/{obj.id}_curve.png"
            buf.description = markdown.markdown(obj.description)
            buf.ztf_id = obj.ztf_id
            buf.id = obj.id
            im_ids.append(buf)
    except:
        user = None
        data = None
        im_ids = None
    context = {
        "user": user,
        "request": request,
        "table": data,
        "token": request.cookies.get('access_token') if not user is None else '',
        "count": len(data) if not data is None else 0,
        "tiles": im_ids,
        'tiles_count': len(im_ids) if im_ids is not None else 0
    }
    return templates.TemplateResponse("index.html", context)

users = {}

@bot.message_handler(commands=['help'])
def help(message):
    help_message = """Доступны следующие команды:
/start старт бота
/connect связать логин в базе с аккаунтом телеграмма
"""
    bot.send_message(message.from_user.id, help_message)


@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.from_user.id, "Здравствуйте! Используйте /connect для связи бота со своим аккаунтом в базе")


@bot.message_handler(commands=['connect'])
def model(message):
    bot.send_message(message.from_user.id, "Введите логин в базе")
    users[message.from_user.id] = {}
    bot.register_next_step_handler(message, save_login)

def save_login(message):
    user, tg_id = message.text, message.from_user.id
    users[tg_id]['name'] = user
    bot.send_message(message.from_user.id, "Введите пароль")
    bot.register_next_step_handler(message, save_password)

def save_password(message):
    password, tg_id = message.text, message.from_user.id
    r = requests.post('https://anomaly.fink-broker.org:443/user/connect', json={
        'name': users[tg_id]['name'],
        'password': password,
        'tg_id': tg_id
    })
    if r.status_code != 200:
        bot.send_message(message.from_user.id, f'Сервер вернул ошибку {r.status_code}. Текст ошибки: {r.text}')
    else:
        bot.send_message(message.from_user.id, f'Логин {users[tg_id]["name"]} успешно связан с tg_id {tg_id}')




if __name__ == '__main__':
    keypath = "certs/privkey.pem"
    certpath = "certs/fullchainl.pem"
    if os.path.isfile(keypath) and os.path.isfile(certpath):
        uvicorn.run("main:app", host="0.0.0.0", port=443, reload=True,
            ssl_keyfile=keypath,
            ssl_certfile=certpath)
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
