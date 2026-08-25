from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """将明文密码转换成不可逆的密码哈希。"""
    if not password:
        raise ValueError("Password cannot be empty")

    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """检查明文密码是否与数据库中的密码哈希匹配。"""
    if not password or not password_hash:
        return False

    try:
        return _password_hash.verify(password, password_hash)
    except UnknownHashError:
        return False
