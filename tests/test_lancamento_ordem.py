class TestCasamentoAlunosIndependenteDeOrdem:
    """Casa aluno da planilha com o SGE por NOME, nao por posicao/ordem."""

    def test_pick_best_student_slot_fora_de_ordem_alfabetica(self):
        from lancar_notas_sge import _pick_best_student_slot

        slots = [
            {"suffix": "0003", "aluno": "PEDRO HENRIQUE SANTOS"},
            {"suffix": "0001", "aluno": "ANA OLIVEIRA"},
            {"suffix": "0002", "aluno": "MARIA SILVA"},
        ]
        alvo = "maria silva"
        escolhido = _pick_best_student_slot(alvo, slots)
        assert escolhido is not None
        assert escolhido["suffix"] == "0002"

    def test_pick_best_student_slot_ignora_ordem_do_portal(self):
        from lancar_notas_sge import _pick_best_student_slot

        slots = [
            {"suffix": "0007", "aluno": "BRUNO LIMA"},
            {"suffix": "0001", "aluno": "ANA OLIVEIRA"},
            {"suffix": "0003", "aluno": "CARLOS PEREIRA"},
            {"suffix": "0002", "aluno": "JOÃO CARLOS SANTOS"},
        ]
        alvo = "joao carlos santos"
        escolhido = _pick_best_student_slot(alvo, slots)
        assert escolhido is not None
        assert escolhido["suffix"] == "0002"

    def test_pick_best_student_slot_sem_falso_positivo(self):
        from lancar_notas_sge import _pick_best_student_slot

        slots = [
            {"suffix": "0001", "aluno": "ANA OLIVEIRA"},
            {"suffix": "0002", "aluno": "MARIA SILVA"},
        ]
        alvo = "jose ricardo almeida"
        assert _pick_best_student_slot(alvo, slots) is None

    def test_candidate_suffixes_prefere_match_exato_independente_da_ordem(self):
        from lancar_notas_sge import _candidate_suffixes_for_student

        slots = [
            {"suffix": "0005", "aluno": "LUCAS FERREIRA"},
            {"suffix": "0001", "aluno": "ANA OLIVEIRA"},
            {"suffix": "0002", "aluno": "MARIA SILVA"},
            {"suffix": "0004", "aluno": "LUCAS FERREIRA"},
        ]
        alvo = "lucas ferreira"
        candidatos = _candidate_suffixes_for_student(alvo, slots)
        assert candidatos[0] == "0005"

    def test_match_nome_com_acento_e_sem_acento(self):
        from lancar_notas_sge import _student_name_matches

        assert _student_name_matches("jose ribamar da conceicao", "JOSÉ RIBAMAR DA CONCEIÇÃO")
        assert _student_name_matches("Ana Oliveira", "ANA OLIVEIRA")
        assert not _student_name_matches("Ana Oliveira", "ANALU PEREIRA")

    def test_match_nome_curto(self):
        from lancar_notas_sge import _student_name_matches

        assert _student_name_matches("joao", "JOÃO CARLOS SANTOS")
        assert not _student_name_matches("joao", "JOSE CARLOS SANTOS")


class TestCasamentoProgressivoPorPrimeiroNome:
    """Busca pelo primeiro nome e desambigua com 2o/3o nome (opcao da IA)."""

    def _enable(self):
        import lancar_notas_sge as mod

        self._mod = mod
        self._old = mod._PRIMEIRO_NOME_MATCH_ENABLED
        mod._PRIMEIRO_NOME_MATCH_ENABLED = True

    def _disable(self):
        self._mod._PRIMEIRO_NOME_MATCH_ENABLED = self._old

    def test_primeiro_nome_unico_casa_mesmo_com_sobrenome_corrompido(self):
        from lancar_notas_sge import _candidate_suffixes_for_student

        self._enable()
        try:
            slots = [
                {"suffix": "0001", "aluno": "MILLENA SILVA"},
                {"suffix": "0002", "aluno": "LUIZ CARLOS PEREIRA"},
                {"suffix": "0003", "aluno": "HELOISA MARTINS"},
            ]
            alvo = "millena sllva"  # sobrenome lido errado pela IA
            candidatos = _candidate_suffixes_for_student(alvo, slots)
            assert candidatos[0] == "0001"
        finally:
            self._disable()

    def test_mesmo_primeiro_nome_desambigua_com_segundo_nome(self):
        from lancar_notas_sge import _candidate_suffixes_for_student

        self._enable()
        try:
            slots = [
                {"suffix": "0001", "aluno": "JOAO PEREIRA"},
                {"suffix": "0002", "aluno": "JOAO SOUZA"},
                {"suffix": "0003", "aluno": "ANA OLIVEIRA"},
            ]
            alvo = "joao souza"  # primeiro nome igual, segundo desambigua
            candidatos = _candidate_suffixes_for_student(alvo, slots)
            assert candidatos[0] == "0002"
        finally:
            self._disable()

    def test_mesmo_primeiro_e_segundo_nome_desambigua_com_terceiro(self):
        from lancar_notas_sge import _candidate_suffixes_for_student

        self._enable()
        try:
            slots = [
                {"suffix": "0001", "aluno": "MARIA EDUARDA ALMEIDA"},
                {"suffix": "0002", "aluno": "MARIA EDUARDA BARBOSA"},
                {"suffix": "0003", "aluno": "MARIA CLARA NUNES"},
            ]
            alvo = "maria eduarda barbosa"
            candidatos = _candidate_suffixes_for_student(alvo, slots)
            assert candidatos[0] == "0002"
        finally:
            self._disable()

    def test_sem_primeiro_nome_no_portal_nao_casa_falso(self):
        from lancar_notas_sge import _candidate_suffixes_for_student
        from lancar_notas_sge import _pick_best_student_slot

        self._enable()
        try:
            slots = [
                {"suffix": "0001", "aluno": "ANA OLIVEIRA"},
                {"suffix": "0002", "aluno": "MARIA SILVA"},
            ]
            alvo = "jose ricardo almeida"
            candidatos = _candidate_suffixes_for_student(alvo, slots)
            assert _pick_best_student_slot(alvo, slots) is None
            assert _pick_best_student_slot(alvo, [s for s in slots if s["suffix"] in candidatos]) is None
        finally:
            self._disable()

    def test_modo_ligado_nao_degrada_casamento_por_nome_completo(self):
        from lancar_notas_sge import _candidate_suffixes_for_student

        slots = [
            {"suffix": "0001", "aluno": "LUCAS FERREIRA"},
            {"suffix": "0002", "aluno": "MARIA SILVA"},
        ]
        alvo = "lucas ferreira"
        off = _candidate_suffixes_for_student(alvo, slots)
        self._enable()
        try:
            on = _candidate_suffixes_for_student(alvo, slots)
        finally:
            self._disable()
        assert on[0] == off[0] == "0001"


class TestLoginSgeValidaCredenciaisAntesDeSubmeter:
    """Credenciais invalidas devem dar erro claro SEM tocar o portal."""

    @staticmethod
    def _mock_page():
        from unittest.mock import MagicMock

        return MagicMock()

    def test_cpf_curto_levanta_erro_claro_sem_tocar_page(self):
        from lancar_notas_sge import LancamentoError, _login_sge

        page = self._mock_page()
        try:
            _login_sge(page, cpf="99748010", senha="123456", logger=None)
            assert False, "deveria ter levantado LancamentoError"
        except LancamentoError as exc:
            assert "CPF" in str(exc) or "digit" in str(exc)
        page.goto.assert_not_called()

    def test_cpf_vazio_levanta_erro_claro(self):
        from lancar_notas_sge import LancamentoError, _login_sge

        page = self._mock_page()
        try:
            _login_sge(page, cpf="", senha="123456", logger=None)
            assert False, "deveria ter levantado LancamentoError"
        except LancamentoError as exc:
            assert "vazio" in str(exc).lower() or "cpf" in str(exc).lower()
        page.goto.assert_not_called()

    def test_senha_vazia_levanta_erro_claro(self):
        from lancar_notas_sge import LancamentoError, _login_sge

        page = self._mock_page()
        try:
            _login_sge(page, cpf="00997748010", senha="   ", logger=None)
            assert False, "deveria ter levantado LancamentoError"
        except LancamentoError as exc:
            assert "senha" in str(exc).lower()
        page.goto.assert_not_called()

    def test_cpf_com_pontos_e_tracos_e_normalizado(self):
        from lancar_notas_sge import _normalize_cpf_for_sge

        assert _normalize_cpf_for_sge("009.977.480-10", logger=None) == "00997748010"

    def test_senha_placeholder_detectada(self):
        from lancar_notas_sge import _looks_like_placeholder_senha

        for senha in ["123456", "12345678", "senha", "teste", "12345", "Test"]:
            assert _looks_like_placeholder_senha(senha), f"deveria detectar '{senha}'"
        assert not _looks_like_placeholder_senha("Me@9senha!")
        assert not _looks_like_placeholder_senha("")


class TestVoltarAposPaginaErrada:
    """Apos clicar num icone que abriu pagina errada, o bot volta antes de tentar o proximo."""

    @staticmethod
    def _mock_page(url):
        from unittest.mock import MagicMock

        page = MagicMock()
        page.url = url
        page.get_by_text.return_value.count.return_value = 0
        return page

    def test_volta_em_pagina_de_adaptacao(self):
        from lancar_notas_sge import _voltar_apos_pagina_errada

        page = self._mock_page("https://www.sge8147.com.br/hportalprofadaptacao.aspx")
        _voltar_apos_pagina_errada(page, logger=None)
        page.go_back.assert_called()

    def test_nao_volta_em_pagina_correta(self):
        from lancar_notas_sge import _voltar_apos_pagina_errada

        page = self._mock_page("https://www.sge8147.com.br/hdisciplinaturmaaluno.aspx")
        _voltar_apos_pagina_errada(page, logger=None)
        page.go_back.assert_not_called()

    def test_nao_volta_em_pagina_neutra(self):
        from lancar_notas_sge import _voltar_apos_pagina_errada

        page = self._mock_page("https://www.sge8147.com.br/hportalprofessor.aspx")
        _voltar_apos_pagina_errada(page, logger=None)
        page.go_back.assert_not_called()

    def test_pagina_de_periodo_nao_e_considerada_errada(self):
        from lancar_notas_sge import _is_wrong_assessment_page

        page = self._mock_page("https://www.sge8147.com.br/hportalprofperiodos.aspx")
        assert not _is_wrong_assessment_page(page)

    def test_pagina_de_periodo_nao_dispara_go_back(self):
        from lancar_notas_sge import _voltar_apos_pagina_errada

        page = self._mock_page("https://www.sge8147.com.br/hportalprofperiodos.aspx")
        _voltar_apos_pagina_errada(page, logger=None)
        page.go_back.assert_not_called()
