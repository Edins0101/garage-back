import os

# Los tests nunca tocan la base real: forzamos SQLite en memoria antes de importar la app.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ALLOW_DEV_LOGIN"] = "true"
os.environ["JWT_SECRET"] = "test-secret-de-al-menos-32-caracteres-para-hs256"
os.environ["EMAIL_PROVIDER"] = "console"
os.environ["REQUIRE_EMAIL_VERIFICATION"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, get_db  # noqa: E402
from app.email import _console  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    _console.outbox.clear()
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def login(client: TestClient, email: str, name: str = "Test") -> dict:
    """Inicia sesión con /auth/dev y devuelve los headers con el token."""
    response = client.post("/api/auth/dev", json={"email": email, "name": name})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def last_code(email: str) -> str:
    """Código de 6 dígitos del último correo enviado (modo consola) a esa dirección."""
    message = next(m for m in reversed(_console.outbox) if m.to == email)
    return message.subject.split()[0]


def register(client: TestClient, email: str, name: str = "Test", password: str = "secreta123"):
    """Flujo completo de registro: pedir código y crear la cuenta con él."""
    assert client.post("/api/auth/codes", json={"email": email, "purpose": "register"}).status_code == 202
    return client.post(
        "/api/auth/register",
        json={"name": name, "email": email, "password": password, "code": last_code(email.lower())},
    )
