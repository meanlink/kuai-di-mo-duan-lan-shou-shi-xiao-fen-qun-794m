from fastapi import APIRouter, Depends

from . import quota
from .auth import allow, current_user
from .db import session
from .quota_schemas import QuotaPlan
from .schemas import Window, validate_window

router = APIRouter()


@router.get('/shift-quotas')
def shift_quotas(region: str | None = None, window: Window = Depends(), db=Depends(session),
                 _user=Depends(current_user)):
    return quota.ledger(db, validate_window(window), region)


@router.put('/shift-quotas')
def save_quota(payload: QuotaPlan, db=Depends(session), user=Depends(allow('admin'))):
    return quota.save_quota(db, payload, user.username)
