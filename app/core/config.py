from typing import Optional
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Management API"

    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_NAME: str = "postgres"
    DB_PORT: int = 6543            # transaction pooler (app)
    DB_MIGRATION_PORT: int = 5432  # session pooler (Alembic)
    DB_SSLMODE: str = "require"

    WEBHOOK_SECRET: Optional[str] = None

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Business timezone: punches are grouped into days and times are returned in this zone
    APP_TIMEZONE: str = "Asia/Kolkata"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.APP_TIMEZONE)

    def _url(self, port: int) -> URL:
        # URL.create escapes special characters in the password safely
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=port,
            database=self.DB_NAME,
            query={"sslmode": self.DB_SSLMODE},
        )

    @property
    def database_url(self) -> URL:
        return self._url(self.DB_PORT)

    @property
    def migration_url(self) -> URL:
        return self._url(self.DB_MIGRATION_PORT)


settings = Settings()
