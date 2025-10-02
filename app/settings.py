from typing import Optional
from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_TITLE: str = "Docs Generator"
    APP_VERSION: str = "1.0.0"

    ADMIN_CHAT_ID: int
    ADMIN_GREETING_THREAD_ID: Optional[int] = None
    ADMIN_ERRORS_THREAD_ID: Optional[int] = None
    ADMIN_DOCUMENTS_THREAD_ID: Optional[int] = None
    ADMIN_FEEDBACK_THREAD_ID: Optional[int] = None

    SERVICE_ACCOUNT_FILE: str
    DATABASE_URL: SecretStr

    API_URL: HttpUrl

    TELEGRAM_BOT_TOKEN: SecretStr
    TELEGRAM_SECRET: SecretStr

    API_TOKEN: SecretStr

    CONFIG_SPREADSHEET_ID: str

    CONFIG_CACHE_DURATION: int = 300
    DEFAULT_VARIABLE_VALUE: str = "Value"

    MAX_RULE_NAME: int = 32
    MAX_VARIABLE_NAME: int = 32
    MAX_VARIABLE_VALUE: int = 8192

    MAX_DOCUMENT_VARIABLES: int = 1000
    MAX_SAVED_VARIABLES: int = 100

    # JWT settings
    JWT_SECRET: SecretStr
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRES_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRES_DAYS: int = 30
    JWT_ISSUER: Optional[str] = None
    JWT_AUDIENCE: Optional[str] = None

    # Cookie settings for auth
    ACCESS_COOKIE_NAME: str = "access_token"
    REFRESH_COOKIE_NAME: str = "refresh_token"
    COOKIE_DOMAIN: Optional[str] = None
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "lax"  # 'lax' | 'strict' | 'none'
    COOKIE_PATH: str = "/"

    # SMTP settings
    SMTP_HOST: str
    SMTP_PORT: int = 587
    SMTP_USERNAME: str
    SMTP_PASSWORD: SecretStr
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str

    EMAIL_VERIFICATION_TEMPLATE: str = "./app/mail/confirm.handlebars"
    PASSWORD_RESET_TEMPLATE: str = "./app/mail/reset-password.handlebars"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings(**{})
