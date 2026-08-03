class TestSubscriptionRevocation:
    def _create_admin(self, db):
        from bot.models.user import User
        from bot.security.auth import generate_token
        admin = User.query.filter_by(username="revoke_admin").first()
        if not admin:
            admin = User(username="revoke_admin", email="revoke_admin@test.com", profile="admin")
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()
        return generate_token(admin)

    def test_revoke_sends_message_reason_and_link(self, client, db):
        token = self._create_admin(db)
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post("/api/admin/payments/create-manual", headers=headers, json={
            "name": "Maria Teste",
            "email": "maria@test.com",
            "cpf": "12345678901",
            "plan": "basico",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        license_key = data["license_key"]
        payment_id = data["payment"]["id"]

        resp = client.post(f"/api/admin/payments/{payment_id}/revoke", headers=headers, json={
            "reason": "Falta de pagamento da mensalidade",
        })
        assert resp.status_code == 200
        assert resp.get_json()["message"] == "Assinatura revogada"
        assert "email_sent" in resp.get_json()

        resp = client.post("/api/license/public-validate", json={"license_key": license_key})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["valid"] is False
        assert "Falta de pagamento da mensalidade" in data["error"]
        assert data["reason"] == "Falta de pagamento da mensalidade"
        assert data["resubscribe_url"] == "https://botdoprofessor.onrender.com/checkout"
        assert "finalizada ou cancelada" in data["error"]

    def test_revoke_is_idempotent(self, client, db):
        token = self._create_admin(db)
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post("/api/admin/payments/create-manual", headers=headers, json={
            "name": "Joao Teste",
            "email": "joao@test.com",
            "cpf": "98765432100",
            "plan": "profissional",
        })
        assert resp.status_code == 201
        payment_id = resp.get_json()["payment"]["id"]

        resp = client.post(f"/api/admin/payments/{payment_id}/revoke", headers=headers, json={
            "reason": "Teste duplicado",
        })
        assert resp.status_code == 200

        resp = client.post(f"/api/admin/payments/{payment_id}/revoke", headers=headers, json={
            "reason": "Teste duplicado",
        })
        assert resp.status_code == 400
        assert "ja esta revogada" in resp.get_json()["error"]

    def test_expired_license_has_resubscribe_link(self, client, db):
        from bot.models.license import License
        from datetime import datetime, timedelta

        lic = License.create(user_id=None, plan="basico", key="EXPIRED-KEY-TEST")
        lic.active = True
        lic.expires_at = datetime.utcnow() - timedelta(days=1)
        db.session.add(lic)
        db.session.commit()

        resp = client.post("/api/license/public-validate", json={"license_key": "EXPIRED-KEY-TEST"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["valid"] is False
        assert "expirada" in data["error"]
        assert data["resubscribe_url"] == "https://botdoprofessor.onrender.com/checkout"
