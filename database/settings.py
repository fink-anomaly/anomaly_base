from pydantic import BaseSettings
from typing import Optional
from database.mongo import initialize_database as mongo_init

class Settings(BaseSettings):
    DATABASE_URL: Optional[str] = None
    SECRET_KEY: Optional[str] = None
    TG_TOKEN: Optional[str] = None

    def is_mongo(self):
        return self.DATABASE_URL.startswith("mongodb://")

    async def initialize_database(self):
        if self.DATABASE_URL.startswith("mongodb://"):
            await mongo_init(self)

    class Config:
        env_file = ".env"
