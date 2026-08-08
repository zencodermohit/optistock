from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "OptiStock"
    DATABASE_URL: str = (
        "postgresql://optistock:optistock_password@127.0.0.1:5433/optistock_db"
    )
    REDIS_URL: str = "redis://localhost:6379/0"
    # No default — app MUST crash if SECRET_KEY is missing in production.
    # For local dev, set it in the .env file.
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Where the nightly ETL writes Parquet. Must be backed by a Docker volume in
    # any deployed environment or the analytical history is destroyed on restart.
    DATA_LAKE_DIR: str = "data_lake"
    # Trailing window the demand forecast reads. Also the divisor for average
    # daily velocity, so it must be a fixed span rather than "days that had sales".
    FORECAST_LOOKBACK_DAYS: int = 30
    FORECAST_HORIZON_DAYS: int = 7

    # .env is shared between this application and docker-compose.yml, which needs
    # infrastructure variables the app does not own (POSTGRES_PASSWORD, PGADMIN_*).
    # Ignore anything undeclared here rather than refusing to boot; the fields
    # above are still validated, and SECRET_KEY is still mandatory.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
