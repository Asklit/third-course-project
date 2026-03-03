from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "lms-core"
    database_url: str = "postgresql://lms:lms@postgres:5432/lms"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_minutes: int = 60 * 24 * 7
    wiki_base_url: str = "http://wiki:8001"
    callback_url: str = ""
    submissions_dir: str = "/data/submissions"


settings = Settings()
