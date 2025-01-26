from typing import List
import datetime
from database import Database
from fastapi import APIRouter, HTTPException, status, Depends
from models.base_types import reaction, update_reaction, ObjectId
from auth.authenticate import authenticate
import aiohttp
import os
import json

reactions_router = APIRouter(
    tags=["Reactions"]
)

reactions = Database(reaction)

MODEL_SERVICE_IP = os.getenv('MODEL_SERVICE_IP')

@reactions_router.get("/", response_model=List[reaction])
async def retrieve_all_reactions() -> List[reaction]:
    events = await reactions.get_all()
    return events


# @reactions_router.get("/{id}", response_model=List[reaction])
# async def retrieve_reaction(id: str) -> List[reaction]:

#     event = await reactions.find_with_ztfid(reaction.ztf_id)
#     if event:
#         return event
#     raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Reaction with supplied ID does not exist"
#         )

async def fetch_retrain_model(model_name: str, positive: list, negative: list):
    url = f"http://{MODEL_SERVICE_IP}/retrain_model"
    payload = {
        "model_name": model_name,
        "positive": positive,
        "negative": negative
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("status")
            else:
                return f"Error: {response.status} - {await response.text()}"

@reactions_router.get("/retrain_model{model_name}")
async def retrain_model(model_name: str, user: str = Depends(authenticate)):
    events = await reactions.find_with_user(model_name)
    events = await events.to_list()
    events = [dict(obj) for obj in events]
    positive = [obj['ztf_id'] for obj in events if obj['tag'] == 'ANOMALY']
    negative = [obj['ztf_id'] for obj in events if obj['tag'] == 'NOT ANOMALY']
    return await fetch_retrain_model(model_name, positive, negative)

@reactions_router.post("/new")
async def create_reaction(new_reaction: reaction, user: str = Depends(authenticate)) -> dict:
    
    if not 'changed_at' in new_reaction: 
        new_reaction.changed_at = str(datetime.datetime.now())
    event = await reactions.find_with_ztfid(new_reaction.ztf_id)
    if event:
        await event.set({reaction.tag: new_reaction.tag})
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
