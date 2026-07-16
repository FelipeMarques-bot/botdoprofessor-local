import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestAuth:
    def test_login_success(self, client, db):
        from bot.models.user import User
        user = User(username="testuser", email="test@test.com", profile="operador")
        user.set_password("test123")
        db.session.add(user)
        db.session.commit()

        resp = client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "test123",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "token" in data
        assert data["user"]["username"] == "testuser"

    def test_login_wrong_password(self, client, db):
        from bot.models.user import User
        user = User(username="testuser", email="test@test.com", profile="operador")
        user.set_password("test123")
        db.session.add(user)
        db.session.commit()

        resp = client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "wrong",
        })
        assert resp.status_code == 401

    def test_me_without_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_token(self, client, db):
        from bot.models.user import User
        from bot.security.auth import generate_token
        user = User(username="testuser", email="test@test.com", profile="operador")
        user.set_password("test123")
        db.session.add(user)
        db.session.commit()

        token = generate_token(user)
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_change_password(self, client, db):
        from bot.models.user import User
        from bot.security.auth import generate_token
        user = User(username="testuser", email="test@test.com", profile="operador")
        user.set_password("test123")
        db.session.add(user)
        db.session.commit()

        token = generate_token(user)
        resp = client.post("/api/auth/change-password", json={
            "old_password": "test123",
            "new_password": "newpass123",
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


class TestLicense:
    def _get_token(self, client, db, profile="operador"):
        from bot.models.user import User
        from bot.security.auth import generate_token
        user = User(username=f"lictest_{profile}", email=f"{profile}@test.com", profile=profile)
        user.set_password("test123")
        db.session.add(user)
        db.session.commit()
        return generate_token(user)

    def test_validate_no_license(self, client, db):
        token = self._get_token(client, db)
        resp = client.get("/api/license/validate", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["valid"] is False

    def test_activate_license(self, client, db):
        token = self._get_token(client, db)
        resp = client.post("/api/license/activate", json={
            "license_key": "TEST-KEY-1234",
            "plan": "1ano",
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_validate_after_activate(self, client, db):
        token = self._get_token(client, db)
        client.post("/api/license/activate", json={
            "license_key": "TEST-KEY-1234",
            "plan": "1ano",
        }, headers={"Authorization": f"Bearer {token}"})

        resp = client.get("/api/license/validate", headers={"Authorization": f"Bearer {token}"})
        data = resp.get_json()
        assert data["valid"] is True
        assert data["days_remaining"] > 0


class TestAdmin:
    def _get_admin_token(self, client, db):
        from bot.models.user import User
        from bot.security.auth import generate_token
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = User(username="admin", email="admin@test.com", profile="admin")
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()
        return generate_token(admin)

    def test_list_users(self, client, db):
        token = self._get_admin_token(client, db)
        resp = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_create_user(self, client, db):
        token = self._get_admin_token(client, db)
        resp = client.post("/api/admin/users", json={
            "username": "newuser",
            "email": "new@test.com",
            "password": "pass123",
            "profile": "operador",
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 201


class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200


class TestCrypto:
    def test_encrypt_decrypt(self):
        from bot.security.crypto import encrypt_value, decrypt_value
        original = "minha_senha_secreta_123"
        encrypted = encrypt_value(original)
        assert encrypted != original
        decrypted = decrypt_value(encrypted)
        assert decrypted == original

    def test_sanitize_log(self):
        from bot.security.crypto import sanitize_log
        data = {"password": "secret123", "username": "admin", "cpf": "12345678901"}
        sanitized = sanitize_log(data)
        assert sanitized["password"] != "secret123"
        assert sanitized["cpf"] != "12345678901"
        assert sanitized["username"] == "admin"

    def test_mask_cpf(self):
        from bot.security.crypto import mask_cpf
        masked = mask_cpf("12345678901")
        assert masked != "12345678901"
        assert "***" in masked


class TestLicenseService:
    def test_generate_key(self):
        from bot.core.license_service import LicenseService
        key1 = LicenseService.generate_key()
        key2 = LicenseService.generate_key()
        assert key1 != key2
        assert len(key1) == 32

    def test_machine_fingerprint(self):
        from bot.core.license_service import LicenseService
        fp = LicenseService.get_machine_fingerprint()
        assert len(fp) == 64


class TestPortalMemory:
    def test_memory_save_load(self, tmp_path):
        from bot.core.portal_memory import PortalMemory, MEMORY_DIR
        import bot.core.portal_memory as pm_mod

        original = pm_mod.MEMORY_DIR
        pm_mod.MEMORY_DIR = tmp_path / "portal_memory"
        try:
            mem = PortalMemory("TestPortal")
            mem.record_success("fill_grade", "input[name='nota']")
            mem.record_column(1, "N1S")

            mem2 = PortalMemory("TestPortal")
            assert mem2.data["success_count"] == 1
            assert mem2.data["columns"]["1"] == "N1S"
        finally:
            pm_mod.MEMORY_DIR = original

    def test_record_failure(self, tmp_path):
        from bot.core.portal_memory import PortalMemory
        import bot.core.portal_memory as pm_mod
        original = pm_mod.MEMORY_DIR
        pm_mod.MEMORY_DIR = tmp_path / "portal_memory"
        try:
            mem = PortalMemory("TestFail")
            mem.record_failure("save", "btn#save", "not found")
            assert mem.data["failure_count"] == 1
            assert len(mem.data["errors_known"]) == 1
        finally:
            pm_mod.MEMORY_DIR = original

    def test_get_best_selector(self, tmp_path):
        from bot.core.portal_memory import PortalMemory
        import bot.core.portal_memory as pm_mod
        original = pm_mod.MEMORY_DIR
        pm_mod.MEMORY_DIR = tmp_path / "portal_memory"
        try:
            mem = PortalMemory("TestBest")
            mem.record_success("fill", "input.nota1")
            mem.record_success("fill", "input.nota1")
            mem.record_success("fill", "input.nota2")
            best = mem.get_best_selector("fill")
            assert best == "input.nota1"
        finally:
            pm_mod.MEMORY_DIR = original


class TestEngine:
    def test_engine_run_basic(self, tmp_path):
        from bot.core.engine import BotEngine
        from bot.core.portal_adapter import PortalContext

        class DummyAdapter:
            name = "Dummy"
            def fill_grade(self, aluno, nota, coluna=""):
                return True
            def save(self):
                return True
            def read_grades(self):
                return []

        engine = BotEngine(DummyAdapter(), execution_id="test-001")
        grades = [
            {"aluno": "Joao", "nota": "8.5"},
            {"aluno": "Maria", "nota": "7.0"},
        ]
        result = engine.run(grades)
        assert result.filled == 2
        assert result.failed == 0
        assert result.success is True

    def test_engine_run_with_failures(self):
        from bot.core.engine import BotEngine

        class FailAdapter:
            name = "Fail"
            def fill_grade(self, aluno, nota, coluna=""):
                return aluno != "Maria"
            def save(self):
                return True
            def read_grades(self):
                return []

        engine = BotEngine(FailAdapter())
        grades = [
            {"aluno": "Joao", "nota": "8.5"},
            {"aluno": "Maria", "nota": "7.0"},
        ]
        result = engine.run(grades)
        assert result.filled == 1
        assert result.failed == 1

    def test_engine_skip_ni(self):
        from bot.core.engine import BotEngine

        class DummyAdapter:
            name = "Dummy"
            def fill_grade(self, aluno, nota, coluna=""):
                return True
            def save(self):
                return True

        engine = BotEngine(DummyAdapter())
        grades = [
            {"aluno": "Joao", "nota": "NI"},
            {"aluno": "Maria", "nota": "I"},
            {"aluno": "Pedro", "nota": ""},
        ]
        result = engine.run(grades)
        assert result.skipped == 3
        assert result.filled == 0

    def test_engine_stats(self):
        from bot.core.engine import BotEngine

        class DummyAdapter:
            name = "TestPortal"
            def fill_grade(self, aluno, nota, coluna=""):
                return True
            def save(self):
                return True

        engine = BotEngine(DummyAdapter())
        engine.run([{"aluno": "A", "nota": "8"}])
        stats = engine.get_stats()
        assert stats["total_runs"] == 1
        assert stats["total_filled"] == 1


class TestPortalFactory:
    def test_get_sge_adapter(self):
        from bot.core.portal_factory import get_adapter
        adapter = get_adapter("SGE")
        assert adapter.name == "SGE"

    def test_get_unknown_portal(self):
        from bot.core.portal_factory import get_adapter
        adapter = get_adapter("PortalDesconhecidoXYZ")
        assert adapter.name == "PortalDesconhecidoXYZ"

    def test_list_portals(self):
        from bot.core.portal_factory import list_portals
        portals = list_portals()
        assert isinstance(portals, list)


class TestLearningTracker:
    def test_record_attempt(self, tmp_path):
        from bot.core.learning import LearningTracker
        import bot.core.portal_memory as pm_mod
        original = pm_mod.MEMORY_DIR
        pm_mod.MEMORY_DIR = tmp_path / "portal_memory"
        try:
            tracker = LearningTracker("TestLearn")
            tracker.record_attempt("fill_grade", "input.nota", True)
            tracker.record_attempt("fill_grade", "input.nota", False, "timeout")
            stats = tracker.memory.get_stats()
            assert stats["success_count"] == 1
            assert stats["failure_count"] == 1
        finally:
            pm_mod.MEMORY_DIR = original

    def test_suggest_fixes(self, tmp_path):
        from bot.core.learning import LearningTracker
        import bot.core.portal_memory as pm_mod
        original = pm_mod.MEMORY_DIR
        pm_mod.MEMORY_DIR = tmp_path / "portal_memory"
        try:
            tracker = LearningTracker("TestSuggest")
            for _ in range(5):
                tracker.record_attempt("fill", "input.bad", False, "not found")
            suggestions = tracker.suggest_fixes()
            assert len(suggestions) > 0
        finally:
            pm_mod.MEMORY_DIR = original


class TestBackupManager:
    def test_create_backup(self, tmp_path):
        from bot.ops.monitoring import BackupManager
        mgr = BackupManager()
        mgr.BACKUP_DIR = tmp_path / "backups"
        path = mgr.create_backup(label="test")
        assert os.path.exists(path)

    def test_list_backups(self, tmp_path):
        from bot.ops.monitoring import BackupManager
        mgr = BackupManager()
        mgr.BACKUP_DIR = tmp_path / "backups"
        mgr.create_backup(label="listtest")
        backups = mgr.list_backups()
        assert len(backups) >= 1


class TestHealthChecker:
    def test_full_check(self):
        from bot.ops.monitoring import HealthChecker
        checker = HealthChecker()
        result = checker.full_check()
        assert "database" in result
        assert "disk" in result


class TestErrorHandlers:
    def test_404(self, client):
        resp = client.get("/api/nonexistent")
        assert resp.status_code == 404

    def test_health_returns_all_checks(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert "database" in data
        assert "disk" in data


class TestMaskLicenseKey:
    def test_mask_long_key(self):
        from bot.security.crypto import mask_license_key
        masked = mask_license_key("ABCDEFGHIJKLMNOP")
        assert masked != "ABCDEFGHIJKLMNOP"
        assert "***" in masked

    def test_mask_short_key(self):
        from bot.security.crypto import mask_license_key
        masked = mask_license_key("AB")
        assert masked == "***"
