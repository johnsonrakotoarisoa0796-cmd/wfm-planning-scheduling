"""Tests d'intégration du flux d'authentification complet.

Utilise une base SQLite en mémoire (override de la dependency get_session)
et le TestClient FastAPI, qui gère les cookies entre requêtes comme un vrai
navigateur — ce qui permet de tester le parcours login -> 2FA -> session.
"""

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_session
from app.core.security import hash_password
from app.main import app
from app.models.enums import UserRole
from app.models.user import User

TEST_PASSWORD = "mot-de-passe-solide-123"


@pytest.fixture()
def engine():
    # StaticPool : une base SQLite ":memory:" n'existe que le temps d'une
    # connexion. Sans StaticPool, chaque Session(engine) ouvrirait une
    # connexion (donc une base) différente et ne verrait pas les tables
    # créées par les autres fixtures.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def client(engine):
    def _get_session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _get_session_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_user(engine):
    secret = pyotp.random_base32()
    with Session(engine) as session:
        user = User(
            email="admin@wfm.local",
            hashed_password=hash_password(TEST_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
            totp_secret=secret,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"id": user.id, "email": user.email, "secret": secret}


@pytest.fixture()
def viewer_user(engine):
    secret = pyotp.random_base32()
    with Session(engine) as session:
        user = User(
            email="viewer@wfm.local",
            hashed_password=hash_password(TEST_PASSWORD),
            role=UserRole.VIEWER,
            is_active=True,
            totp_secret=secret,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"id": user.id, "email": user.email, "secret": secret}


def _login_flow(client: TestClient, email: str, password: str, totp_secret: str):
    """Effectue le parcours complet login -> 2FA et retourne la réponse finale."""
    login_page = client.get("/login")
    assert login_page.status_code == 200
    csrf_token = client.cookies.get("csrf_token")
    assert csrf_token

    step1 = client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert step1.status_code == 303
    assert step1.headers["location"] == "/login/verify"
    assert "pending_2fa" in client.cookies

    verify_page = client.get("/login/verify")
    assert verify_page.status_code == 200
    csrf_token_2 = client.cookies.get("csrf_token")

    code = pyotp.TOTP(totp_secret).now()
    step2 = client.post(
        "/login/verify",
        data={"code": code, "csrf_token": csrf_token_2},
        follow_redirects=False,
    )
    return step2


def test_root_redirects_to_login_when_not_authenticated(client: TestClient):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_full_login_flow_sets_session_cookie(client: TestClient, admin_user):
    final = _login_flow(client, admin_user["email"], TEST_PASSWORD, admin_user["secret"])
    assert final.status_code == 303
    assert final.headers["location"] == "/"
    assert "session" in client.cookies
    # Le cookie temporaire de 2FA doit avoir été nettoyé après succès.
    assert client.cookies.get("pending_2fa") in (None, "")


def test_me_endpoint_after_login(client: TestClient, admin_user):
    _login_flow(client, admin_user["email"], TEST_PASSWORD, admin_user["secret"])
    response = client.get("/me")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == admin_user["email"]
    assert body["role"] == "admin"


def test_wrong_password_shows_error_and_does_not_create_pending_session(client: TestClient, admin_user):
    client.get("/login")
    csrf_token = client.cookies.get("csrf_token")
    response = client.post(
        "/login",
        data={"email": admin_user["email"], "password": "mauvais-mot-de-passe", "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "incorrect" in response.text.lower()
    assert "pending_2fa" not in client.cookies


def test_wrong_totp_code_is_rejected(client: TestClient, admin_user):
    client.get("/login")
    csrf_token = client.cookies.get("csrf_token")
    client.post(
        "/login",
        data={"email": admin_user["email"], "password": TEST_PASSWORD, "csrf_token": csrf_token},
        follow_redirects=False,
    )
    client.get("/login/verify")
    csrf_token_2 = client.cookies.get("csrf_token")
    response = client.post(
        "/login/verify",
        data={"code": "000000", "csrf_token": csrf_token_2},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "session" not in client.cookies


def test_login_post_without_csrf_token_is_rejected(client: TestClient, admin_user):
    client.get("/login")  # pose le cookie csrf_token, mais on ne l'envoie pas dans le form
    response = client.post(
        "/login",
        data={"email": admin_user["email"], "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_logout_clears_session(client: TestClient, admin_user):
    _login_flow(client, admin_user["email"], TEST_PASSWORD, admin_user["secret"])
    csrf_token = client.cookies.get("csrf_token")
    response = client.post("/logout", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    protected = client.get("/", follow_redirects=False)
    assert protected.status_code == 303
    assert protected.headers["location"] == "/login"


def test_rbac_admin_can_access_admin_route(client: TestClient, admin_user):
    _login_flow(client, admin_user["email"], TEST_PASSWORD, admin_user["secret"])
    response = client.get("/admin/ping")
    assert response.status_code == 200


def test_rbac_viewer_cannot_access_admin_route(client: TestClient, viewer_user):
    _login_flow(client, viewer_user["email"], TEST_PASSWORD, viewer_user["secret"])
    response = client.get("/admin/ping")
    assert response.status_code == 403
