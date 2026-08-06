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


class FakeEvalScope:
    def __init__(self, value):
        self._value = value

    def evaluate(self, js, arg=None):
        return self._value


class TestReadGradeValueJs:
    """Leitura via JS so confia quando existe exatamente UM campo casando com o suffix."""

    def test_match_unico_retorna_valor(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeEvalScope("9,2")
        assert m._read_grade_value_js(scope, "0001") == "9,2"

    def test_zero_like_retorna_none(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeEvalScope("0,0")
        assert m._read_grade_value_js(scope, "0001") is None

    def test_sem_match_retorna_none(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeEvalScope(None)
        assert m._read_grade_value_js(scope, "0001") is None

    def test_erro_retorna_none(self, monkeypatch):
        import lancar_notas_sge as m

        class BoomScope:
            def evaluate(self, js, arg=None):
                raise RuntimeError("boom")

        assert m._read_grade_value_js(BoomScope(), "0001") is None


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

    def test_posicao_fora_mapa_varias_colunas_sem_token_retorna_vazio(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeScope({"N1S": 30, "N2S": 30, "N15S": 30, "PE": 30})
        page = FakePage([scope])

        def fake_iter_scopes(page):
            return page._scopes

        monkeypatch.setattr(m, "_iter_scopes", fake_iter_scopes)
        result = m._detect_coluna_from_page(page, posicao_grid=24, atividade="")
        assert result == ""

    def test_posicao_fora_mapa_uma_coluna_distinta_retorna_ela(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeScope({"N2S": 30})
        page = FakePage([scope])

        def fake_iter_scopes(page):
            return page._scopes

        monkeypatch.setattr(m, "_iter_scopes", fake_iter_scopes)
        result = m._detect_coluna_from_page(page, posicao_grid=24, atividade="")
        assert result == "N2S"

    def test_posicao_fora_mapa_token_atividade_vence(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeScope({"N1S": 30, "N2S": 30})
        page = FakePage([scope])

        def fake_iter_scopes(page):
            return page._scopes

        monkeypatch.setattr(m, "_iter_scopes", fake_iter_scopes)
        result = m._detect_coluna_from_page(page, posicao_grid=24, atividade="Avaliacao N2S")
        assert result == "N2S"


class TestReadExistingGradeMulticoluna:
    """Leitura de 'nota existente' nao pode ler o valor de OUTRA coluna."""

    def _setup(self, monkeypatch, counts, value="9,2"):
        import lancar_notas_sge as m

        scope = FakeScope(counts)
        page = FakePage([scope])

        def fake_iter_scopes(page):
            return page._scopes

        monkeypatch.setattr(m, "_iter_scopes", fake_iter_scopes)
        monkeypatch.setattr(
            m, "_wait_student_slots",
            lambda scope, attempts=4, delay_ms=200: [{"suffix": "0001", "aluno": "ALUNO A"}],
        )
        monkeypatch.setattr(m, "_candidate_suffixes_for_student", lambda expected, slots: ["0001"])
        monkeypatch.setattr(m, "_read_grade_value_js", lambda scope, suffix, coluna="": value)
        return m, page

    def test_pagina_multicoluna_nao_gera_sge_ja_falso(self, monkeypatch):
        m, page = self._setup(monkeypatch, {"N1S": 30, "N2S": 30, "N15S": 30, "PE": 30})
        result = m._read_existing_grade_for_student(page, "ALUNO A", None, coluna_sge="")
        assert result is None

    def test_pagina_uma_coluna_usa_leitura_sem_filtro(self, monkeypatch):
        m, page = self._setup(monkeypatch, {"N2S": 30})
        result = m._read_existing_grade_for_student(page, "ALUNO A", None, coluna_sge="")
        assert result == "9,2"

    def test_leitura_ambigua_nao_gera_sge_ja(self, monkeypatch):
        m, page = self._setup(monkeypatch, {"N2S": 30}, value=None)
        result = m._read_existing_grade_for_student(page, "ALUNO A", None, coluna_sge="")
        assert result is None

    def test_coluna_definida_ignora_valor_de_outra_coluna(self, monkeypatch):
        m, page = self._setup(monkeypatch, {"N1S": 30, "N2S": 30}, value="8,5")
        result = m._read_existing_grade_for_student(page, "ALUNO A", None, coluna_sge="N2S")
        assert result == "8,5"
