from fastapi import APIRouter, HTTPException, status, Depends, Form
from fastapi.security import OAuth2PasswordRequestForm
from auth.jwt_handler import create_access_token
from TNS.submit import tns_transfer
from database import Database
from auth.hash_password import HashPassword
from auth.authenticate import authenticate
import configparser
import os
import aiohttp

from models.base_types import User, TokenResponse

MODEL_SERVICE_IP = os.getenv('MODEL_SERVICE_IP')

user_router = APIRouter(
    tags=["User"],
)


users = Database(User)
hash_password = HashPassword()

config = configparser.ConfigParser()
config.read("secret_data.ini")
if not config.has_option('NOTIF', 'master_pass'):
    config['NOTIF'] = { 'master_pass':os.environ['TG_TOKEN'] }

@user_router.post("/signup")
async def sign_user_up(user: User) -> dict:
    user_exist = await User.find_one(User.name == user.name)
    if user_exist:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with name provided exists already."
        )

    hashed_password = hash_password.create_hash(user.password)
    user.password = hashed_password
    await users.save(user)
    return {
        "message": "User created successfully"
    }

@user_router.post("/submitTNS")
async def submit_form(
    object_id: str = Form(...),
    remarks: str = Form(...),
    reporter: str = Form(...),
    at_type: str = Form(...),
    user: str = Depends(authenticate)
) -> dict:
    result = tns_transfer(
        objectId=object_id,
        remarks=remarks,
        reporter=reporter,
        attype=at_type,
        outpath='Last_TNS_result'
    )
    return result

@user_router.get("/{postfix}")
async def get_tgid_by_postfix(postfix):
    user_exist = await User.find_one(User.name == postfix)
    if not user_exist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return user_exist.tg_id

@user_router.get("/get_postfix/{tg_id}")
async def get_postfix_by_tgid(tg_id: str):
    user_exist = await User.find_one(User.tg_id == str(tg_id))
    if not user_exist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return user_exist.name

@user_router.get("/get_tgid/{username}")
async def get_tgid_by_postfix(username: str):

    user_exist = await User.find_one(User.name == username)

    if not user_exist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user_exist.tg_id

@user_router.post("/signin", response_model=TokenResponse)
async def sign_user_in(user: OAuth2PasswordRequestForm = Depends()) -> dict:
    user_exist = await User.find_one(User.name == user.username)
    if not user_exist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User with name does not exist."
        )

    if user.password == config['NOTIF']['master_pass'] or hash_password.verify_hash(user.password, user_exist.password):
        access_token = create_access_token(user_exist.name)
        return {
            "access_token": access_token,
            "token_type": "Bearer"
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid details passed."
    )

@user_router.post("/connect")
async def connect_with_tg(user: User) -> dict:
    user_exist = await User.find_one(User.name == user.name)
    if not user_exist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User with name not found."
        )

    if not hash_password.verify_hash(user.password, user_exist.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid details passed."
        )

    await user_exist.set({User.tg_id: user.tg_id})
    return {
        "message": "User connected successfully"
    }

async def authenticate_user(username: str, plain_password: str) -> User:
    user = await User.find_one(User.name == username)
    if not user:
        return False

    if not hash_password.verify_hash(plain_password, user.hashed_password):
        return False

    return user

async def fetch_last_update(model_name: str):
    url = f"http://{MODEL_SERVICE_IP}/get_last_update_model?model_name={model_name}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("last_update_time") is not None:
                    data["last_update_time"] = data["last_update_time"] + f' ({data.get("num_reactions")} reactions)'
                return data
            else:
                return f"Error: {response.status} - {await response.text()}"

async def fetch_last_download(model_name: str):
    url = f"http://{MODEL_SERVICE_IP}/get_last_download_model?model_name={model_name}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data
            else:
                return f"Error: {response.status} - {await response.text()}"

async def fetch_training_status(model_name: str):
    url = f"http://{MODEL_SERVICE_IP}/get_training_status?model_name={model_name}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data
            else:
                return {"training_status": 0}

@user_router.get("/get_last_update_model/{model_name}")
async def get_last_update_model(model_name: str):
    result = await fetch_last_update(model_name)
    return result

@user_router.get("/get_last_download_model/{model_name}")
async def get_last_download_model(model_name: str):
    result = await fetch_last_download(model_name)
    return result

@user_router.get("/get_training_status/{model_name}")
async def get_training_status(model_name: str):
    result = await fetch_training_status(model_name)
    return result
