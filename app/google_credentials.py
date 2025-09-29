from google.oauth2.service_account import Credentials

from app.constants import GOOGLE_AUTH_SCOPES
from app.settings import settings

credentials = Credentials.from_service_account_file(
    settings.SERVICE_ACCOUNT_FILE, scopes=GOOGLE_AUTH_SCOPES
)
