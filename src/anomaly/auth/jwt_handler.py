import time
from datetime import datetime

import routes.users
from database.settings import Settings
from fastapi import HTTPException, status
from jose import jwt, JWTError
from models.base_types import User
from fastapi import Depends, Request
from auth.authenticate import oauth2_scheme_cookie

settings = Settings()


def create_access_token(user: str):
    payload = {
        "user": user,
        "expires": time.time() + 3600*24*30
    }

    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token


def verify_access_token(token: str):
    try:
        data = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])

        expire = data.get("expires")

        if expire is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No access token supplied"
            )
        if datetime.utcnow() > datetime.utcfromtimestamp(expire):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token expired!"
            )
        return data

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token"
        )


async def get_user(username):
    user = await routes.users.User.find_one(routes.users.User.name == username)
    return user


async def cookie_decode_token(token: str) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials"
    )

    try:
        token = token.removeprefix("Bearer").strip()
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        username: str = payload.get("user")
        if username is None:
            raise credentials_exception
    except JWTError as e:
        raise credentials_exception
    except Exception as e:
        return None
    

    user = await routes.users.User.find_one(routes.users.User.name == username)
    return user


async def get_current_user_from_token(token: str = Depends(oauth2_scheme_cookie)) -> User:
    """
    Get the current user from the cookies in a request.

    Use this function when you want to lock down a route so that only
    authenticated users can see access the route.
    """
    user = await cookie_decode_token(token)
    return user


async def get_current_user_from_cookie(request: Request) -> User:
    """
    Get the current user from the cookies in a request.

    Use this function from inside other routes to get the current user. Good
    for views that should work for both logged in, and not logged in users.
    """
    token = request.cookies.get('access_token')
    user = await cookie_decode_token(token)
    return user
