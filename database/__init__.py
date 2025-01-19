from database.settings import Settings
if Settings().is_mongo():
    from database.mongo import Database
else:
    from database.sqlalchemy import Database
