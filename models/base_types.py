from pydantic import BaseModel
from typing import List, Optional
from sqlmodel import JSON, SQLModel, Field, Column
from fastapi import APIRouter
from beanie import Document


class reaction(Document):
    id: str
    tag: str
    user: str
    changed_at: Optional[str] = None
    
    class Config:
        scheme_extra = {
            "example": {
            'id': 'ZTF18aazmwmw',
            'tag': 'Anomaly',
            'user': 'Anastasia',
            'changed_at': '22.11.2023 17:50'
            }
        }
    
    class Settings:
        name = "events"


class update_reaction(BaseModel):
    id: Optional[str]
    tag: Optional[str]
    user: Optional[str]
    changed_at: Optional[str]
    
    class Config:
        scheme_extra = {
            "example": {
            'id': 'ZTF18aazmwmw',
            'tag': 'Anomaly',
            'user': 'Anastasia',
            'changed_at': '22.11.2023 17:50'
            }
        }
        
class User(Document):
    name: str
    password: str
    
    class Settings:
        name = "users"
    
    class Config:
        scheme_extra = {
            "example": {
            'name': 'Anastasia',
            'password': '0000'
            }
        }
        

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
