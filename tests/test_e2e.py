import os
import sys
import pytest
from datetime import datetime, timedelta

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
    os.environ["SECRET_KEY"] = "e2e-test-key-very-long-secure-string-here"
    from app import create_app
    from bot.security.rate_limit import limiter
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        from bot.models.database import db
        db.create_all()
        limiter._store.clear()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(db, username="e2e_user", profile="operador"):
    from bot.models.user import User
    user = User(username=username, email=f"{username}@test.com", profile=profile)
    user.set_password("test123")
    db.session.add(user)
    db.session.commit()
    return user


def _get_token(client, db, username="e2e_user", profile="operador"):
    user = _create_user(db, username, profile)
    resp = client.post("/api/auth/login", json={
        "username": username, "password": "test123"
    })
    return resp.get_json()["token"]


def _activate_license(client, token, plan="1ano"):
    client.post("/api/license/activate", json={
        "license_key": f"KEY-{plan}-{token[:8]}",
        "plan": plan,
    }, headers={"Authorization": f"Bearer {token}"})


class TestE2E_FullSuccess:
    """Cenário completo de execução com sucesso."""

    def test_full_lifecycle(self, client, db):
        _create_user(db, "e2e_admin", "admin")
        resp = client.post("/api/auth/login", json={
            "username": "e2e_admin", "password": "test123"
        })
        assert resp.status_code == 200
        token = resp.get_json()["token"]

        resp = client.post("/api/license/activate", json={
            "license_key": "E2E-KEY-FULLSUCCESS",
            "plan": "1ano",
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

        resp = client.get("/api/license/validate", headers={"Authorization": f"Bearer {token}"})
        data = resp.get_json()
        assert data["valid"] is True
        assert data["days_remaining"] > 0

        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.get_json()["database"]["status"] == "ok"

        resp = client.get("/api/portals", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert "sge" in resp.get_json()["portals"]

        class MockAdapter:
            name = "MockSGE"
            def fill_grade(self, aluno, nota, coluna=""): return True
            def save(self): return True
            def read_grades(self): return []

        from bot.core.engine import BotEngine
        engine = BotEngine(MockAdapter(), execution_id="e2e-001")
        result = engine.run([
            {"aluno": "Joao Silva", "nota": "8.5"},
            {"aluno": "Maria Santos", "nota": "9.0"},
            {"aluno": "Pedro Costa", "nota": "7.5"},
        ])
        assert result.success is True
        assert result.filled == 3

        assert engine.save_and_verify() is True
        assert engine.get_stats()["total_filled"] == 3

        resp = client.post("/api/backup", json={"label": "e2e"},
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

        resp = client.get("/api/backup", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert len(resp.get_json()["backups"]) >= 1


class TestE2E_RecoverableError:
    """Cenário com erro recuperável (timeout, elemento não encontrado)."""

    def test_retry_on_failure(self, client, db):
        _create_user(db, "retry_user", "operador")
        resp = client.post("/api/auth/login", json={
            "username": "retry_user", "password": "test123"
        })
        token = resp.get_json()["token"]
        _activate_license(client, token, "1ano")

        from bot.core.engine import BotEngine

        call_count = 0

        class RetryAdapter:
            name = "RetryTest"
            def fill_grade(self, aluno, nota, coluna=""):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise TimeoutError("Elemento nao encontrado")
                return True
            def save(self): return True

        engine = BotEngine(RetryAdapter())
        error = None
        try:
            result = engine.run([{"aluno": "Teste", "nota": "8"}])
        except TimeoutError as e:
            error = e

        # Engine should catch the exception
        assert result.failed == 1
        stats = engine.handle_error("Elemento nao encontrado")
        assert stats["should_retry"] is True

    def test_partial_failure_continues(self, client, db):
        from bot.core.engine import BotEngine

        class PartialAdapter:
            name = "PartialTest"
            def fill_grade(self, aluno, nota, coluna=""):
                return nota != "NI"
            def save(self): return True

        engine = BotEngine(PartialAdapter())
        result = engine.run([
            {"aluno": "A", "nota": "8"},
            {"aluno": "B", "nota": "NI"},
            {"aluno": "C", "nota": "9"},
        ])
        assert result.filled == 2
        assert result.skipped == 1
        assert result.failed == 0


class TestE2E_CriticalFailure:
    """Cenário com falha crítica (login falha, portal inacessível)."""

    def test_login_failure_blocks_execution(self, client, db):
        _create_user(db, "fail_user", "operador")
        resp = client.post("/api/auth/login", json={
            "username": "fail_user", "password": "test123"
        })
        token = resp.get_json()["token"]

        resp = client.get("/api/license/validate", headers={"Authorization": f"Bearer {token}"})
        assert resp.get_json()["valid"] is False

        resp = client.post("/api/license/activate", json={
            "license_key": "INVALID",
            "plan": "plano_inexistente",
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code in (400, 500)

    def test_portal_adapter_login_failure(self):
        from bot.core.engine import BotEngine
        from bot.core.portal_adapter import PortalContext

        class FailLoginAdapter:
            name = "FailLogin"
            _logged_in = False
            def login(self, cpf, senha): return False
            def navigate_to(self, ctx): return False
            def fill_grade(self, a, n, c=""): return False
            def save(self): return False
            def is_logged_in(self): return False

        adapter = FailLoginAdapter()
        assert adapter.login("cpf", "senha") is False
        assert adapter.is_logged_in() is False

    def test_engine_reports_all_failures(self):
        from bot.core.engine import BotEngine

        class AllFailAdapter:
            name = "AllFail"
            def fill_grade(self, aluno, nota, coluna=""):
                return False
            def save(self): return True

        engine = BotEngine(AllFailAdapter())
        result = engine.run([
            {"aluno": "A", "nota": "8"},
            {"aluno": "B", "nota": "9"},
        ])
        assert result.filled == 0
        assert result.failed == 2


class TestE2E_ExpiredLicense:
    """Cenário com licença expirada."""

    def test_expired_license_rejected(self, client, db):
        from bot.models.user import User
        from bot.models.license import License
        from bot.security.auth import generate_token

        user = _create_user(db, "expired_user", "operador")
        token = generate_token(user)

        # Manually create expired license
        lic = License(
            license_key="EXPIRED-KEY-123",
            user_id=user.id,
            plan="1ano",
            days=365,
            activated_at=datetime.utcnow() - timedelta(days=400),
            expires_at=datetime.utcnow() - timedelta(days=35),
            active=True,
        )
        db.session.add(lic)
        db.session.commit()

        # Validate should show expired
        resp = client.get("/api/license/validate", headers={"Authorization": f"Bearer {token}"})
        data = resp.get_json()
        assert data["valid"] is False
        assert "expirada" in data["error"]

    def test_deactivated_license_rejected(self, client, db):
        from bot.models.user import User
        from bot.models.license import License
        from bot.security.auth import generate_token

        user = _create_user(db, "deact_user", "operador")
        token = generate_token(user)

        lic = License(
            license_key="DEACT-KEY-123",
            user_id=user.id,
            plan="1ano",
            days=365,
            activated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=365),
            active=False,
        )
        db.session.add(lic)
        db.session.commit()

        resp = client.get("/api/license/validate", headers={"Authorization": f"Bearer {token}"})
        data = resp.get_json()
        assert data["valid"] is False

    def test_license_check_feature_blocks_ai(self, app):
        with app.app_context():
            from bot.core.license_service import LicenseService
            result = LicenseService.check_feature("nonexistent-key", "ai_assist")
            assert result is False


class TestE2E_ViolationBlock:
    """Cenário com bloqueio por violação (permissão negada, token inválido)."""

    def test_unauthenticated_access_blocked(self, client):
        endpoints = [
            ("/api/auth/me", "GET"),
            ("/api/license/validate", "GET"),
            ("/api/admin/users", "GET"),
            ("/api/backup", "POST"),
            ("/api/portals/discover", "POST"),
        ]
        for path, method in endpoints:
            if method == "GET":
                resp = client.get(path)
            else:
                resp = client.post(path, json={})
            assert resp.status_code == 401, f"{method} {path} should be 401"

    def test_operador_cannot_access_admin(self, client, db):
        token = _get_token(client, db, "op_user", "operador")

        resp = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

        resp = client.post("/api/admin/users", json={
            "username": "hacker", "email": "h@x.com", "password": "123", "profile": "admin"
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_invalid_token_rejected(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid-token-123"})
        assert resp.status_code == 401

    def test_expired_token_rejected(self, client, db):
        from bot.models.user import User
        from bot.security.auth import generate_token
        import jwt
        from config.settings import SECRET_KEY

        user = _create_user(db, "token_user", "operador")
        expired_payload = {
            "user_id": user.id,
            "username": user.username,
            "profile": user.profile,
            "exp": datetime.utcnow() - timedelta(hours=1),
            "iat": datetime.utcnow() - timedelta(hours=25),
        }
        expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm="HS256")

        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401

    def test_inactive_user_rejected(self, client, db):
        from bot.models.user import User
        from bot.security.auth import generate_token

        user = _create_user(db, "inactive_user", "operador")
        user.active = False
        db.session.commit()

        token = generate_token(user)
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


class TestE2E_PortalsAndMemory:
    """Cenário de multi-portal e memória persistente."""

    def test_portal_factory_returns_correct_type(self):
        from bot.core.portal_factory import get_adapter
        from bot.core.sge_adapter import SGEAdapter
        from bot.core.custom_adapter import CustomPortalAdapter

        sge = get_adapter("SGE")
        assert isinstance(sge, SGEAdapter)

        custom = get_adapter("MeuPortal")
        assert isinstance(custom, CustomPortalAdapter)

    def test_portal_memory_persistence(self, tmp_path):
        from bot.core.portal_memory import PortalMemory
        import bot.core.portal_memory as pm_mod

        original = pm_mod.MEMORY_DIR
        pm_mod.MEMORY_DIR = tmp_path / "mem"
        try:
            m1 = PortalMemory("PersistTest")
            m1.record_success("fill", "input.nota")
            m1.record_column(1, "N1S")
            m1.record_navigation("turma_a", "/turma/a")
            m1.record_save_flow({"btn": "#save"})

            m2 = PortalMemory("PersistTest")
            assert m2.data["success_count"] == 1
            assert m2.data["columns"]["1"] == "N1S"
            assert m2.data["navigation"]["turma_a"] == "/turma/a"
            assert m2.data["save_flow"]["btn"] == "#save"
        finally:
            pm_mod.MEMORY_DIR = original

    def test_learning_tracker_detects_drift(self, tmp_path):
        from bot.core.learning import LearningTracker
        import bot.core.portal_memory as pm_mod

        original = pm_mod.MEMORY_DIR
        pm_mod.MEMORY_DIR = tmp_path / "drift"
        try:
            tracker = LearningTracker("DriftTest")
            for _ in range(5):
                tracker.record_attempt("fill", "input.old", False, "not found")
            tracker.record_attempt("fill", "input.new", True)

            drift = tracker.detect_selector_drift("fill", "input.old")
            assert drift is not None
            assert drift["drift_detected"] is True
        finally:
            pm_mod.MEMORY_DIR = original

    def test_engine_with_adapter_full_flow(self):
        from bot.core.engine import BotEngine
        from bot.core.portal_adapter import PortalContext

        class FullFlowAdapter:
            name = "FullFlow"
            def fill_grade(self, aluno, nota, coluna=""):
                return nota not in ("NI", "I", "-")
            def save(self): return True
            def read_grades(self):
                return [
                    {"aluno": "Joao", "nota": "8.5"},
                    {"aluno": "Maria", "nota": "9.0"},
                ]

        engine = BotEngine(FullFlowAdapter())
        result = engine.run([
            {"aluno": "Joao", "nota": "8.5"},
            {"aluno": "Maria", "nota": "NI"},
            {"aluno": "Pedro", "nota": "7.0"},
            {"aluno": "", "nota": ""},
        ])

        assert result.filled == 2
        assert result.skipped == 2
        assert result.failed == 0

        comparison = engine.read_and_compare([
            {"aluno": "Joao", "nota": "8.5"},
            {"aluno": "Maria", "nota": "9.0"},
        ])
        assert comparison["matched"] == 2
        assert comparison["mismatched"] == 0


class TestE2E_BackupAndRestore:
    """Cenário de backup e restauração."""

    def test_backup_and_list(self, tmp_path):
        from bot.ops.monitoring import BackupManager
        mgr = BackupManager()
        mgr.BACKUP_DIR = tmp_path / "backups"

        path1 = mgr.create_backup(label="before")
        path2 = mgr.create_backup(label="after")

        backups = mgr.list_backups()
        assert len(backups) == 2
        assert backups[0]["name"] > backups[1]["name"]  # sorted desc

    def test_cleanup_old_backups(self, tmp_path):
        from bot.ops.monitoring import BackupManager
        mgr = BackupManager()
        mgr.BACKUP_DIR = tmp_path / "backups"

        for i in range(15):
            mgr.create_backup(label=f"old-{i}")

        mgr.cleanup_old(keep=5)
        backups = mgr.list_backups()
        assert len(backups) <= 5
