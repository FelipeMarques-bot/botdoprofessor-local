class TestColunaSge:
    """Extrai a coluna correta de nota no SGE a partir da atividade e da pagina."""

    def test_token_n1s(self):
        from lancar_notas_sge import _coluna_token_from_atividade

        assert _coluna_token_from_atividade("N1S") == "n1s"
        assert _coluna_token_from_atividade("Avaliacao N1S") == "n1s"
        assert _coluna_token_from_atividade("n1s") == "n1s"

    def test_token_pe(self):
        from lancar_notas_sge import _coluna_token_from_atividade

        assert _coluna_token_from_atividade("PE") == "pe"
        assert _coluna_token_from_atividade("Prova Escrita PE") == "pe"

    def test_token_nota_1(self):
        from lancar_notas_sge import _coluna_token_from_atividade

        assert _coluna_token_from_atividade("NOTA 1") == "nota1"
        assert _coluna_token_from_atividade("Atividade Nota 2") == "nota2"

    def test_sem_token(self):
        from lancar_notas_sge import _coluna_token_from_atividade

        assert _coluna_token_from_atividade("Avaliacao") == ""

    def test_norm_coluna(self):
        from lancar_notas_sge import _norm_coluna

        assert _norm_coluna("N1S") == "n1s"
        assert _norm_coluna("NOTA 1") == "nota1"
        assert _norm_coluna("PE") == "pe"


class FakeScope:
    def __init__(self, counts):
        self._counts = counts

    def evaluate(self, js):
        return dict(self._counts)


class FakePage:
    def __init__(self, scopes):
        self._scopes = scopes
        self.frames = []

    def evaluate(self, js):
        return {}

    def _iter_scopes_helper(self):
        return self._scopes


class TestDetectColunaFromPage:
    def test_prefere_coluna_da_atividade(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeScope({"N1S": 30, "N2S": 30, "N15S": 30, "PE": 30})
        page = FakePage([scope])

        def fake_iter_scopes(page):
            return page._scopes

        monkeypatch.setattr(m, "_iter_scopes", fake_iter_scopes)
        result = m._detect_coluna_from_page(page, posicao_grid=2, atividade="N2S")
        assert result == "N2S"

    def test_empatia_sem_atividade_usa_default(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeScope({"N1S": 30, "N2S": 30, "N15S": 30, "PE": 30})
        page = FakePage([scope])

        def fake_iter_scopes(page):
            return page._scopes

        monkeypatch.setattr(m, "_iter_scopes", fake_iter_scopes)
        result = m._detect_coluna_from_page(page, posicao_grid=2, atividade="")
        assert result == "N2S"

    def test_sem_padroes_retorna_vazio(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeScope({})
        page = FakePage([scope])

        def fake_iter_scopes(page):
            return page._scopes

        monkeypatch.setattr(m, "_iter_scopes", fake_iter_scopes)
        result = m._detect_coluna_from_page(page, posicao_grid=4, atividade="")
        assert result == ""

    def test_mais_comum_como_fallback(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeScope({"N1S": 1, "N2S": 30})
        page = FakePage([scope])

        def fake_iter_scopes(page):
            return page._scopes

        monkeypatch.setattr(m, "_iter_scopes", fake_iter_scopes)
        result = m._detect_coluna_from_page(page, posicao_grid=2, atividade="")
        assert result == "N2S"
