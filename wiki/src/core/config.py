from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "lms-wiki"
    mongo_url: str = "mongodb://mongo:27017"
    mongo_db: str = "lms_wiki"
    mongo_collection: str = "labs"


settings = Settings()
