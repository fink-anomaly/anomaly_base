from database.settings import Settings

if Settings().is_mongo():
    from models.mongo import ImageDocument, reaction, update_reaction, User, TokenResponse, ObjectId
else:
    from models.sqlalchemy import ImageDocument, reaction, update_reaction, User, TokenResponse, ObjectId
