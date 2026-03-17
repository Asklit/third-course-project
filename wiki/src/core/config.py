from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "lms-wiki"
    mongo_url: str = "mongodb://mongo:27017"
    mongo_db: str = "lms_wiki"
    mongo_collection: str = "labs"
    meili_enabled: bool = True
    meili_url: str = "http://meilisearch:7700"
    meili_api_key: str = ""
    meili_index: str = "wiki_sections"


settings = Settings()
