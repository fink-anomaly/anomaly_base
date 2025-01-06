from pydantic_settings import BaseSettings
from typing import Optional
from database.mongo import initialize_database as mongo_init

class Settings(BaseSettings):
    DATABASE_URL: Optional[str] = None
    SECRET_KEY: Optional[str] = None
    TG_TOKEN: Optional[str] = None
    DEBUG: Optional[str] = None

    def is_mongo(self):
        return self.DATABASE_URL.startswith("mongodb://")

    async def initialize_database(self):
        if self.DATABASE_URL.startswith("mongodb://"):
            await mongo_init(self)
        else:
            from sqlmodel import create_engine
            from database.sqlalchemy import Base
            engine = create_engine(self.DATABASE_URL, echo=not not self.DEBUG )
            Base.engine = engine
            Base.metadata.create_all(engine)

    class Config:
        env_file = ".env"
        extra = 'allow'
