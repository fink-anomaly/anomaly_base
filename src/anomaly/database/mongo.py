from typing import Any, List, Optional

from beanie import init_beanie, PydanticObjectId
from models.mongo import reaction, User, ImageDocument
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

async def initialize_database(Settings):
   client = AsyncIOMotorClient(Settings.DATABASE_URL)
   await init_beanie(database=client.db_name,
                     document_models=[reaction, User, ImageDocument])

class Database:
    def __init__(self, model):
        self.model = model

    async def save(self, document) -> None:
        await document.create()
        return

    async def get(self, id: str) -> Any:
        doc = await self.model.get(id)
        if doc:
            return doc
        return False

    async def get_all(self) -> List[Any]:
        docs = await self.model.find_all().to_list()
        return docs

    async def update(self, id: PydanticObjectId, body: BaseModel) -> Any:
        doc_id = id
        des_body = body.dict()

        des_body = {k: v for k, v in des_body.items() if v is not None}
        update_query = {"$set": {
            field: value for field, value in des_body.items()
        }}

        doc = await self.get(doc_id)
        if not doc:
            return False
        await doc.update(update_query)
        return doc

    async def delete(self, id: PydanticObjectId) -> bool:
        doc = await self.get(id)
        if not doc:
            return False
        await doc.delete()
        return True
    
    async def delete_all_with_user(self, user: str) -> bool:
        search_result = self.model.find({"user": user})
        if not (await search_result.count() > 0):
            return False
        await search_result.delete()
        return True

    async def find_with_user(self, name: str) -> List:
        search_result = self.model.find_many({"user": name}) if name != 'admin' else self.model.find_all()
        return search_result

    async def find_with_ztfid(self, ztf_id: str, user: str) -> Any:
        search_result = self.model.find_one({'ztf_id': ztf_id, 'user': user})
        if await search_result.count():
            return search_result
        return False

    async def find_with_tgid(self, tg_id: str) -> Any:
        search_result = self.model.find_one({'tg_id': tg_id})
        if await search_result.count():
            return search_result
        return None
