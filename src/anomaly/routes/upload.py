from contextlib import contextmanager
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import UploadFile, Form
from database import Database
from fastapi import APIRouter, HTTPException, status, Depends, Response
from models.base_types import ImageDocument, ObjectId
from auth.authenticate import authenticate
from loguru import logger

image_router = APIRouter(
    tags=["Uploads"]
)

images = Database(ImageDocument)


def image_paths(image_id):
    return [Path('static') / f'{image_id}_{kind}.png' for kind in ('curve', 'cutout')]


@contextmanager
def publish_images(staged, image_id):
    published = []
    try:
        for source, target in zip(staged, image_paths(image_id)):
            source.replace(target)
            published.append(target)
        yield
    except BaseException:
        # Also undo publication if the database write is cancelled.
        for path in published:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception('Could not remove incomplete notification file {}', path)
        raise


def remove_images(image_id):
    for path in image_paths(image_id):
        path.unlink(missing_ok=True)


@image_router.post("/upload")
async def upload_images(ztf_id: str, candid_id: str, image1: UploadFile, image2: UploadFile, description: str = Form(...), user: str = Depends(authenticate)):
    image1_bytes = await image1.read()
    image2_bytes = await image2.read()

    image_doc = ImageDocument(
        description=description,
        ztf_id=ztf_id,
        user=user,
        candid_id=candid_id
    )
    try:
        with TemporaryDirectory(prefix='.upload-', dir='static') as directory:
            staged = [Path(directory) / name for name in ('curve.png', 'cutout.png')]
            for path, content in zip(staged, (image1_bytes, image2_bytes)):
                path.write_bytes(content)
            await images.save(image_doc, publication=partial(publish_images, staged))
    except Exception:
        logger.exception('Could not store notification images')
        raise HTTPException(status_code=500, detail='Could not store notification images.') from None

    return {
        "message": "Images uploaded successfully",
        "id": str(image_doc.id)
    }


@image_router.get("/get_image/{image_id}/{image_number}")
async def get_image(image_id: str, image_number: int):
    image_doc = await ImageDocument.get(image_id)
    if image_doc:
        if image_number == 1:
            return Response(content=image_doc.image1, media_type="image/png")
        elif image_number == 2:
            return Response(content=image_doc.image2, media_type="image/png")
    return Response(status_code=404)


@image_router.delete("/{num}")
async def delete_reaction(num: ObjectId, user: str = Depends(authenticate)) -> dict:
    try:
        event = await images.delete_owned(num, user, cleanup=partial(remove_images, num))
    except OSError:
        logger.exception('Could not remove files for notification {}', num)
        raise HTTPException(status_code=500, detail='Could not remove notification images.') from None
    if event:
        return {
            "message": "Reaction (image) deleted successfully"
        }
    raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reaction (image) with supplied ID does not exist"
    )
