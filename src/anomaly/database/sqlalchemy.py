from typing import ClassVar
from sqlalchemy import engine
from sqlmodel import Field, Session, SQLModel, select, insert, update, delete

from loguru import logger

def Database(cls):
    return cls

class Base(SQLModel, table=False):
    engine: ClassVar[engine] = None
    class rows(list):
        async def to_list(self):
            return self

    @classmethod
    async def get_all(cls):
        with Session(cls.engine) as sess:
            return sess.execute(select(cls)).all()

    @classmethod
    async def find_one(cls, expr):
        with Session(cls.engine) as sess:
            return sess.execute(select(cls).where(expr)).scalar()

    @classmethod
    async def save(cls, inst):
        with Session(cls.engine) as sess:
            sess.add(inst)
            sess.commit()
            sess.refresh(inst)

    async def set(self, changes):
        with Session(self.engine) as sess:
            sess.query(self.__class__).filter(self.__class__.id==self.id).update(changes)
            sess.commit()

    @classmethod
    async def find_with_user(cls, name):
        with Session(cls.engine) as sess:
            return cls.rows( [ i for (i,) in sess.execute(select(cls).where(cls.user == name)).all() ] )

    @classmethod
    async def find_with_ztfid(cls, ztfid, user):
        return await cls.find_one({'ztf_id': ztfid, 'user': user})

    @classmethod
    async def get(cls, id):
        return await cls.find_one({"id": id})

    @classmethod
    async def delete(cls, oid):
        o = await cls.get(oid)

        if not o:
            return False

        with Session(cls.engine) as sess:
            sess.execute(delete(cls).where({"id": oid}))
            sess.commit()
        return True

        
class User(Base, table=True):
    __tablename__ = "users"
    id: int | None  = Field (default=None, primary_key=True)
    name: str
    password: str
    tg_id: str | None = None


class ImageDocument(Base, table=True):
    __tablename__ = "images"
    id: int | None  = Field (default=None, primary_key=True)
    description: str
    ztf_id: str
    user: str

class TokenResponse(Base, table=True):
    __tablename__ = "tokens"
    id: int | None  = Field (default=None, primary_key=True)
    access_token: str
    token_type: str

class reaction(Base, table=True):
    __tablename__ = "reactions"

    id: int | None  = Field (default=None, primary_key=True)
    ztf_id: str
    tag: str
    user: str | None
    changed_at: str | None

update_reaction = reaction
