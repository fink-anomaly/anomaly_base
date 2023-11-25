from pydantic import BaseModel
from typing import List, Optional
from sqlmodel import JSON, SQLModel, Field, Column



class reaction(SQLModel, table=True):
    num: int = Field(default=None, primary_key=True)
    id: str
    tag: str
    user: str
    changed_at: str
    
    class Config:
        scheme_extra = {
            "example": {
            'id': 'ZTF18aazmwmw',
            'tag': 'Anomaly',
            'user': 'Anastasia',
            'changed_at': '22.11.2023 17:50'
            }
        }


class update_reaction(SQLModel):
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
        
class User(BaseModel):
    name: str
    password: str
    
    class Config:
        scheme_extra = {
            "example": {
            'name': 'Anastasia',
            'password': '0000'
            }
        }
        

class UserSignIn(BaseModel):
    name: str
    password: str
    
    class Config:
        scheme_extra = {
            "example": {
            'name': 'Anastasia',
            'password': '0000'
            }
        }