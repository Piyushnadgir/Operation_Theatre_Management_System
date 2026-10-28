from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "OTMS"
    debug: bool = True
    database_url: str = "sqlite:///./otms.db"
    secret_key: str = "dev-secret-key-change-in-prod"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


settings = Settings()
