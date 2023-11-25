from typing import List

from fastapi import APIRouter, Body, HTTPException, status, Depends, Request
from models.base_types import reaction, update_reaction
from database.connection import get_session

reactions_router = APIRouter(
    tags=["Events"]
)

reactions = []



@reactions_router.get("/", response_model=List[reaction])
async def retrieve_all_reactions(session=Depends(get_session)) -> List[reaction]:
    statement = select(reaction)
    events = session.exec(statement).all()
    return events

@reactions_router.get("/{id}", response_model=List[reaction])
async def retrieve_reaction(id: str, session=Depends(get_session)) -> List[reaction]:

    event = session.get(reaction, id)
    if event:
        return event
    raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reaction with supplied ID does not exist"
        )


@reactions_router.post("/new")
async def create_event(new_reaction: reaction,
            session=Depends(get_session)) -> dict:
    session.add(new_reaction)
    session.commit()
    session.refresh(new_reaction)
    return {
        "message": "Reaction added successfully"
    }


@reactions_router.delete("/delete/{num}")
async def delete_event(num: int, session=Depends(get_session)) -> dict:
    event = session.get(reaction, num)
    if event:
        session.delete(event)
        session.commit()
        return {
            "message": "Reaction deleted successfully"
        }
    raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reaction with supplied ID does not exist"
    )



@reactions_router.put("/edit/{num}", response_model=reaction)
async def update_event(num: int, new_data: update_reaction,
                        session=Depends(get_session)) -> reaction:
    event = session.get(reaction, num)
    if event:
        event_data = new_data.dict(exclude_unset=True)
        for key, value in event_data.items():
            setattr(event, key, value)
        session.add(event)
        session.commit()
        session.refresh(event)
        return event
    raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reaction with supplied ID does not exist"
    )