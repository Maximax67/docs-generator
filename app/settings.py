from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_TITLE: str = "Docs Generator"
    APP_VERSION: str = "1.0.0"

    SERVICE_ACCOUNT_FILE: str
    DATABASE_URL: SecretStr

    API_URL: HttpUrl
    FRONTEND_URL: HttpUrl
    ALLOWED_ORIGINS: str

    MAX_VARIABLE_NAME: int = 100
    MAX_DOCUMENT_VARIABLES: int = 1000

    MAX_FILE_DOWNLOAD_SIZE: int | None = None
    MAX_PROCESS_MEMORY: int | None = None
    MAX_PROCESS_CPU_TIME: int | None = None
    MAX_CONVERSION_TIME: int | None = None

    JWT_SECRET: SecretStr
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRES_MINUTES: int = 10
    REFRESH_TOKEN_EXPIRES_DAYS: int = 30
    JWT_ISSUER: str | None = None
    JWT_AUDIENCE: str | None = None

    ACCESS_COOKIE_NAME: str = "access_token"
    REFRESH_COOKIE_NAME: str = "refresh_token"
    COOKIE_DOMAIN: str | None = None
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "lax"  # 'lax' | 'strict' | 'none'

    MAILER_URL: str
    MAILER_TOKEN: SecretStr

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings(**{})
