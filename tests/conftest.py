import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    from bot.security.rate_limit import limiter
    limiter._store.clear()
    yield
    limiter._store.clear()


@pytest.fixture
def app():
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["SECRET_KEY"] = "test-key-123"
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    from bot.models.database import db as _db, init_db
    with app.app_context():
        _db.create_all()
        yield _db
        _db.drop_all()
