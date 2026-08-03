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
