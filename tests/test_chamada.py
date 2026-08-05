class TestMontarPlano:
    def test_pula_ja_lancado_e_presenca_nao_altera(self):
        from bot.core.sge_chamada_adapter import (
            RegistroAluno, montar_plano, _resumo_plano,
        )

        grade = [
            RegistroAluno(indice="0001", nome="ANA LÍVIA PROENÇA DE LIMA", ja_lancado=True),
            RegistroAluno(indice="0002", nome="ANTONY GABRIEL DAVILA", ja_lancado=False),
            RegistroAluno(indice="0003", nome="BRUNA CAROLINY DA SILVA MABA", ja_lancado=False),
        ]
        foto = [
            {"aluno": "Antony Gabriel Davila", "situacao": "presente"},
            {"aluno": "BRUNA CAROLINY", "situacao": "falta_justificada", "motivo": "atestado_medico"},
        ]
        plano = montar_plano(grade, foto)
        acoes = {item.aluno.nome: item.acao for item in plano}

        assert acoes["ANA LÍVIA PROENÇA DE LIMA"] == "pular"
        assert acoes["ANTONY GABRIEL DAVILA"] == "presenca"
        assert acoes["BRUNA CAROLINY DA SILVA MABA"] == "falta"

        just = next(i for i in plano if i.aluno.nome.startswith("BRUNA"))
        assert just.motivo == "1"
        assert just.motivo_nome == "Atestado Medico"

        resumo = _resumo_plano(plano)
        assert resumo == {"ja_lancados": 1, "presentes": 1, "faltas": 1, "pulados": 0}

    def test_falta_injustificada_padrao(self):
        from bot.core.sge_chamada_adapter import RegistroAluno, montar_plano

        grade = [RegistroAluno(indice="0001", nome="GUILHERME HENRIQUE MAAS", ja_lancado=False)]
        foto = [{"aluno": "GUILHERME MAAS", "situacao": "falta", "faltas": 2}]
        plano = montar_plano(grade, foto)
        item = plano[0]
        assert item.acao == "falta"
        assert item.motivo == "2"
        assert item.faltas == 2

    def test_nome_sem_match_vai_para_nao_encontrados(self):
        from bot.core.sge_chamada_adapter import RegistroAluno, montar_plano

        grade = [RegistroAluno(indice="0001", nome="MARIA SILVA", ja_lancado=False)]
        foto = [{"aluno": "PESSOA DESCONHECIDA", "situacao": "falta"}]
        plano = montar_plano(grade, foto)
        assert plano[0].acao == "pular"
        assert plano[0].aluno.ja_lancado is False

    def test_suspensao_e_obito_mapeiam_codigos(self):
        from bot.core.sge_chamada_adapter import RegistroAluno, montar_plano

        grade = [
            RegistroAluno(indice="0001", nome="A", ja_lancado=False),
            RegistroAluno(indice="0002", nome="B", ja_lancado=False),
        ]
        foto = [
            {"aluno": "A", "situacao": "falta_justificada", "motivo": "suspensao"},
            {"aluno": "B", "situacao": "falta_justificada", "motivo": "obito"},
        ]
        plano = montar_plano(grade, foto)
        motivos = {i.aluno.nome: i.motivo for i in plano}
        assert motivos["A"] == "11"
        assert motivos["B"] == "7"


class TestExtractChamadaRecords:
    def test_parse_resposta_com_code_fence(self):
        from ai_assist import _extract_chamada_records

        txt = """```json
        {"data":"05/08/2026","alunos":[
          {"aluno":"Ana Lima","situacao":"presente","faltas":0,"motivo":""},
          {"aluno":"Bruno Maas","situacao":"falta","faltas":2,"motivo":""},
          {"aluno":"Carla Souza","situacao":"FJ","faltas":1,"motivo":"atestado médico"}
        ]}
        ```"""
        registros = _extract_chamada_records(txt)
        by_name = {r["aluno"]: r for r in registros}
        assert by_name["Ana Lima"]["situacao"] == "presente"
        assert by_name["Bruno Maas"]["situacao"] == "falta"
        assert by_name["Bruno Maas"]["faltas"] == "2"
        assert by_name["Carla Souza"]["situacao"] == "falta_justificada"
        assert by_name["Carla Souza"]["motivo"] == "atestado_medico"

    def test_ignora_linhas_ilegiveis(self):
        from ai_assist import _extract_chamada_records

        txt = '{"alunos":[{"aluno":"","situacao":"presente"},{"aluno":"X","situacao":"talvez"}]}'
        registros = _extract_chamada_records(txt)
        assert registros == []

    def test_normalizacao_situacao_simbolos(self):
        from ai_assist import _normalize_chamada_situacao

        assert _normalize_chamada_situacao(".") == "presente"
        assert _normalize_chamada_situacao("C") == "presente"
        assert _normalize_chamada_situacao("F") == "falta"
        assert _normalize_chamada_situacao("x") == "falta"
        assert _normalize_chamada_situacao("J") == "falta_justificada"
        assert _normalize_chamada_situacao("F.J.") == "falta_justificada"


class TestImageChamadaExtractor:
    def test_extract_chamada_from_image(self, monkeypatch):
        import ai_assist
        from bot.utils import image_chamada_extractor as ice

        def fake_ai(prompt, image_bytes, logger=None):
            return (
                '{"data":"05/08/2026","alunos":['
                '{"aluno":"Ana Lima","situacao":"presente","faltas":0,"motivo":""},'
                '{"aluno":"Bruno Maas","situacao":"falta","faltas":1,"motivo":""}]}'
            )

        monkeypatch.setattr(ai_assist, "_call_ai_with_fallback", fake_ai)
        result = ice.extract_chamada_from_image(b"fake-image-bytes")
        assert result["total_encontrados"] == 2
        assert result["alunos"][0]["aluno"] == "Ana Lima"

    def test_prompts_exigem_situacao_e_motivo(self):
        from ai_assist import (
            EXTRAIR_CHAMADA_IMAGEM_PROMPT,
            EXTRAIR_CHAMADA_IMAGEM_REFINAR,
        )

        assert "situacao" in EXTRAIR_CHAMADA_IMAGEM_PROMPT
        assert "falta_justificada" in EXTRAIR_CHAMADA_IMAGEM_PROMPT
        assert "motivo" in EXTRAIR_CHAMADA_IMAGEM_REFINAR
