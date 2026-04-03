from fastapi import APIRouter
router = APIRouter(prefix="/api/context")


@router.get("")
async def list_context():
    return []
