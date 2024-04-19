from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from auth.jwt_handler import create_access_token
from database.connection import Database
from auth.hash_password import HashPassword

from models.base_types import User, TokenResponse

user_router = APIRouter(
    tags=["User"],
)

users = Database(User)
hash_password = HashPassword()


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

@user_router.get("/{postfix}")
async def get_tgid_by_postfix(postfix: str, response_model=str) -> str:

    user_exist = await User.find_one(User.name == postfix)

    if user_exist:
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

    if hash_password.verify_hash(user.password, user_exist.password):
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

    await user_exist.update(
        {"$set":
            {
                'tg_id': user.tg_id
            }
        }
    )
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