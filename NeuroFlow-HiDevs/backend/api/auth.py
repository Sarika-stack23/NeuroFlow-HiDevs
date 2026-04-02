"""JWT authentication — POST /auth/token."""
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from config import settings
from db.pool import get_pool

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class ClientIn(BaseModel):
    client_id: str
    client_secret: str


def create_access_token(client_id: str, scopes: list[str]) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": client_id, "scopes": scopes, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        client_id: str = payload.get("sub", "")
        scopes: list[str] = payload.get("scopes", [])
        if not client_id:
            raise credentials_exc
        return {"client_id": client_id, "scopes": scopes}
    except JWTError:
        raise credentials_exc


def require_scope(scope: str):
    async def dependency(user: Annotated[dict, Depends(get_current_user)]):
        if scope not in user.get("scopes", []):
            raise HTTPException(status_code=403, detail=f"Scope '{scope}' required")
        return user
    return dependency


@router.post("/token", response_model=TokenResponse, summary="Get JWT access token")
async def get_token(body: ClientIn):
    """Exchange client_id + client_secret for a JWT access token."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT client_secret_hash, scopes FROM api_clients WHERE client_id = $1",
        body.client_id,
    )
    if not row or not pwd_context.verify(body.client_secret, row["client_secret_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(body.client_id, list(row["scopes"]))
    return TokenResponse(access_token=token, expires_in=settings.jwt_expire_minutes * 60)
