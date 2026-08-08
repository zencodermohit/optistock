from app.core.security import create_access_token, verify_password, get_password_hash
import jwt
from app.core.config import settings


def test_password_hashing():
    password = "SuperSecretPassword123!"
    hashed = get_password_hash(password)

    assert password != hashed
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_create_access_token():
    data = {"sub": "user-uuid", "role": "warehouse_manager"}
    token = create_access_token(data)

    # Verify the token can be decoded using our secret key
    decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

    assert decoded["sub"] == "user-uuid"
    assert decoded["role"] == "warehouse_manager"
    assert "exp" in decoded  # Ensure expiration was added
