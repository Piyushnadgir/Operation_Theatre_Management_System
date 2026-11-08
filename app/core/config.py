from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "OTMS"
    debug: bool = True
    database_url: str = "sqlite:///./otms.db"
    secret_key: str = "dev-secret-key-change-in-prod"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
<<<<<<< HEAD
=======
    # OT-SR-001: when True, every plain-HTTP request is refused.
    # Set ENFORCE_HTTPS=true in the environment for deployment / the security demo.
    enforce_https: bool = False
>>>>>>> 6d57647 (OTMS-16: Implement login, password hashing, lockout and RBAC middleware)


settings = Settings()
