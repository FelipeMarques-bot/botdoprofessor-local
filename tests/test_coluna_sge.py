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

    def test_strict_ambiguo_retorna_none(self, monkeypatch):
        import lancar_notas_sge as m

        class FakeStrictEvalScope:
            def evaluate(self, js, arg=None):
                if arg and arg.get("strict"):
                    return None
                return "9,2"

        scope = FakeStrictEvalScope()
        assert m._read_grade_value_js(scope, "0001") == "9,2"
        assert m._read_grade_value_js(scope, "0001", strict=True) is None


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
        monkeypatch.setattr(m, "_read_grade_value_js", lambda scope, suffix, coluna="", strict=False: value)
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


class TestGradeFieldMatcher:
    """O filtro de campo de NOTA exclui campos de RECUPERACAO/NOME, senão o
    sufixo '_0002' casa _NOTA_0002 E _NOTAREC_0002 e toda leitura fica
    ambigua ('campo leu vazio' em todas as linhas)."""

    def test_aceita_campo_nota(self):
        from lancar_notas_sge import _grade_field_attr_matches

        assert _grade_field_attr_matches("_NOTA_0002", "0002", "") is True

    def test_exclui_campo_recuperacao(self):
        from lancar_notas_sge import _grade_field_attr_matches

        assert _grade_field_attr_matches("_NOTAREC_0002", "0002", "") is False
        assert _grade_field_attr_matches("_RECUP_0002", "0002", "") is False

    def test_exclui_campo_nome(self):
        from lancar_notas_sge import _grade_field_attr_matches

        assert _grade_field_attr_matches("_ALUMATNOM_0002", "0002", "") is False
        assert _grade_field_attr_matches("_ALUNO_0002", "0002", "") is False

    def test_exclui_sufixo_diferente(self):
        from lancar_notas_sge import _grade_field_attr_matches

        assert _grade_field_attr_matches("_NOTA_0001", "0002", "") is False

    def test_coluna_definida_exige_prefixo_da_coluna(self):
        from lancar_notas_sge import _grade_field_attr_matches

        assert _grade_field_attr_matches("_N2S_0002", "0002", "N2S") is True
        assert _grade_field_attr_matches("_NOTA_0002", "0002", "N2S") is False
