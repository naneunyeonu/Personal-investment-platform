"""
환경 변수 기반 설정 (Pydantic BaseSettings)
.env 파일 또는 OS 환경 변수에서 자동 로드
"""

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 앱 기본 ────────────────────────────────────────────────────────
    APP_NAME: str = "AI Investment Support Platform"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # CORS 허용 오리진
    # - localhost:5173  → Vite 개발 서버 (npm run dev)
    # - localhost:4173  → Vite 프리뷰 서버 (npm run preview)
    # - localhost:3000  → CRA / 기타 개발 서버
    # - 127.0.0.1 변형 → curl / Postman 등 직접 호출 대응
    # 운영 환경: .env에서 ALLOWED_ORIGINS=["https://yourdomain.com"] 로 덮어쓰기
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:4173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
        "http://127.0.0.1:3000",
    ]

    # ── 데이터베이스 ───────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/investment_db",
        description="asyncpg 드라이버 포함 PostgreSQL URL",
    )
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # ── JWT / 보안 ─────────────────────────────────────────────────────
    SECRET_KEY: str = Field(
        default="CHANGE_ME_IN_PRODUCTION_USE_STRONG_RANDOM_KEY",
        min_length=32,
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Redis / Celery ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # ── 외부 API 키 ────────────────────────────────────────────────────
    KIS_APP_KEY: str = ""
    KIS_APP_SECRET: str = ""
    KIS_ACCOUNT_NO: str = ""

    DART_API_KEY: str = ""

    SEC_API_KEY: str = ""

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    # 명시적 캐시 TTL (초) — 어닝스 콜 대본 / 증권사 리포트 등
    GEMINI_CACHE_TTL_SECONDS: int = 3600

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg:// scheme")
        return v


settings = Settings()
