import pytest
from fastapi.testclient import TestClient
from app import app
from jose import jwt

SECRET_KEY = "your-very-secret-key"
ALGORITHM = "HS256"

@pytest.fixture
def client():
    return TestClient(app)

def create_jwt(role="USER", user_id=1):
    payload = {"sub": user_id, "role": role}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def test_create_user(client):
    token = create_jwt(role="USER")
    response = client.post(
        "/api/user/",
        json={"username": "testuser", "email": "test@example.com"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"

def test_create_user_unauthorized(client):
    response = client.post(
        "/api/user/",
        json={"username": "testuser", "email": "test@example.com"},
    )
    assert response.status_code == 401

def test_create_user_forbidden(client):
    token = create_jwt(role="GUEST")
    response = client.post(
        "/api/user/",
        json={"username": "testuser", "email": "test@example.com"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
