"""User Intent Authorization API."""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_user_public_key_pem
from app.policy import verify_intent
from app.schemas import UserIntentCredential

router = APIRouter(prefix="/api/v1/intent", tags=["Intent"])


class AuthorizeIntentRequest(BaseModel):
    intent_jwt: str


@router.post("/authorize", status_code=status.HTTP_201_CREATED, response_model=UserIntentCredential)
def authorize_user_intent(
    req: AuthorizeIntentRequest,
    db: Session = Depends(get_db),
    user_pub: bytes = Depends(get_user_public_key_pem),
) -> UserIntentCredential:
    """Registers and verifies a cryptographic UserIntentCredential signed with user's ES256 key."""
    return verify_intent(intent_jwt=req.intent_jwt, user_public_key_pem=user_pub, db=db)
