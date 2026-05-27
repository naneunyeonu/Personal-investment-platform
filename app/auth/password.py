"""
bcrypt 기반 비밀번호 해시 / 검증 유틸리티
평문 비밀번호는 절대 DB에 저장하지 않음
"""

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """평문 → bcrypt 해시"""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """입력값과 저장된 해시 비교"""
    return _pwd_context.verify(plain, hashed)
