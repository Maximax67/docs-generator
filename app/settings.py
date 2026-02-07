from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_TITLE: str = "Docs Generator"
    APP_VERSION: str = "1.0.0"

    ALLOWED_ORIGINS: str

    ADMIN_CHAT_ID: int
    ADMIN_GREETING_THREAD_ID: int | None = None
    ADMIN_ERRORS_THREAD_ID: int | None = None
    ADMIN_DOCUMENTS_THREAD_ID: int | None = None
    ADMIN_FEEDBACK_THREAD_ID: int | None = None

    ADMIN_GREETING_ENABLED: bool = True

    SERVICE_ACCOUNT_FILE: str
    DATABASE_URL: SecretStr

    API_URL: HttpUrl
    FRONTEND_URL: HttpUrl

    TELEGRAM_BOT_TOKEN: SecretStr
    TELEGRAM_SECRET: SecretStr

    API_TOKEN: SecretStr

    MAX_VARIABLE_NAME: int = 100
    MAX_DOCUMENT_VARIABLES: int = 1000

    MAX_FILE_DOWNLOAD_SIZE: int = 50 * 1024 * 1024
    MAX_PROCESS_MEMORY: int = 256 * 1024 * 1024
    MAX_PROCESS_CPU_TIME: int = 30
    MAX_CONVERSION_TIME: int = 30

    JWT_SECRET: SecretStr
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRES_MINUTES: int = 15
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
