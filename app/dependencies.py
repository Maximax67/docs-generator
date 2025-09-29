from fastapi import HTTPException, Header, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.settings import settings

http_bearer = HTTPBearer()


def verify_token(
    auth: HTTPAuthorizationCredentials = Security(http_bearer),
) -> str:
    token = auth.credentials
    if auth.scheme != "Bearer" or token != settings.API_TOKEN.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token",
        )

    return token


def verify_telegram_token(
    x_telegram_token: str = Header(..., alias="X-Telegram-Bot-Api-Secret-Token")
) -> str:
    if x_telegram_token != settings.TELEGRAM_SECRET.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Telegram token",
        )

    return x_telegram_token
