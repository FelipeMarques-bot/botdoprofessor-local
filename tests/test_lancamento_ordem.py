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
