from typing import List
import datetime
from database.mongo import Database
from fastapi import APIRouter, HTTPException, status, Depends
from models.base_types import reaction, update_reaction, ObjectId
from auth.authenticate import authenticate

reactions_router = APIRouter(
    tags=["Reactions"]
)

reactions = Database(reaction)



@reactions_router.get("/", response_model=List[reaction])
async def retrieve_all_reactions() -> List[reaction]:
    events = await reactions.get_all()
    return events


@reactions_router.get("/{id}", response_model=List[reaction])
async def retrieve_reaction(id: str) -> List[reaction]:

    event = await reactions.find(reaction.ztf_id == id)
    if event:
        return event
    raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reaction with supplied ID does not exist"
        )




@reactions_router.post("/new")
async def create_reaction(new_reaction: reaction, user: str = Depends(authenticate)) -> dict:
    
    if not 'changed_at' in new_reaction: 
        new_reaction.changed_at = str(datetime.datetime.now())
    event = await reactions.find_with_ztfid(new_reaction.ztf_id)
    if event:
        await event.update({"$set": {'tag': new_reaction.tag}})
        return {
        "message": "Updated!"
        }
    new_reaction.user = user
    await reactions.save(new_reaction)
    return {
        "message": "Reaction added successfully"
    }


@reactions_router.delete("/{num}")
async def delete_reaction(num: ObjectId, user: str = Depends(authenticate)) -> dict:
    event = await reactions.delete(num)
    if event:
        return {
            "message": "Reaction deleted successfully"
        }
    raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reaction with supplied ID does not exist"
    )


@reactions_router.delete("/delete_user/{name}")
async def delete_reaction_from_user(name: str, user: str = Depends(authenticate)) -> dict:
    """
    
    """
    event = await reactions.delete_all_with_user(name)
    if event:
        return {
            "message": "Reactions deleted successfully"
        }
    raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reaction with supplied names does not exist"
    )


@reactions_router.put("/{num}", response_model=reaction)
async def update_reaction(num: ObjectId, new_data: update_reaction, user: str = Depends(authenticate)) -> reaction:
    event = await reactions.update(num, new_data)
    if event:
        return event
    raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reaction with supplied ID does not exist"
    )
