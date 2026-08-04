import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _monta_xlsx(path, headers, rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "6 Ano"
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


class TestLeitorDatasXlsx:
    def test_layout_template_datas_agrupadas(self, tmp_path):
        from datetime import datetime
        from leitor_planilhas import ler_notas_excel

        path = tmp_path / "notas.xlsx"
        _monta_xlsx(path, [
            "Escola", "Turno", "Turma", "Trimestre", "Nome do Aluno",
            "Atividade 1", "Atividade 2", "Atividade 3",
            "Data realização 1", "Data realização 2", "Data realização 3",
        ], [
            ["Juvenal", "Matutino", "6º Ano", "2º Trimestre", "Acsa",
             "8,5", "7,0", "9,0",
             datetime(2026, 3, 1), datetime(2026, 4, 15), datetime(2026, 5, 20)],
        ])

        registros = ler_notas_excel(str(path))
        by_act = {r.atividade: r for r in registros}
        assert by_act["Atividade 1"].data_realizacao == "01/03/2026"
        assert by_act["Atividade 2"].data_realizacao == "15/04/2026"
        assert by_act["Atividade 3"].data_realizacao == "20/05/2026"

    def test_layout_usuario_sge(self, tmp_path):
        from datetime import datetime
        from leitor_planilhas import ler_notas_excel

        path = tmp_path / "notas.xlsx"
        _monta_xlsx(path, [
            "Escola", "Turno", "Turma", "Trimestre", "Nome do Aluno",
            "5 - Aula prática", "Data realização 1", "Atividade 2", "Atividade 3",
            "Data realização 2", "Data realização 3",
        ], [
            ["Juvenal", "Matutino", "6º Ano", "2º Trimestre", "Acsa",
             "8,5", datetime(2026, 7, 6), None, None, None, None],
        ])

        registros = ler_notas_excel(str(path))
        assert len(registros) == 1
        reg = registros[0]
        assert reg.atividade == "5 - Aula prática"
        assert reg.nota == 8.5
        assert reg.data_realizacao == "06/07/2026"

    def test_sem_coluna_de_data(self, tmp_path):
        from leitor_planilhas import ler_notas_excel

        path = tmp_path / "notas.xlsx"
        _monta_xlsx(path, [
            "Escola", "Turno", "Turma", "Trimestre", "Nome do Aluno", "Atividade 1",
        ], [
            ["Juvenal", "Matutino", "6º Ano", "2º Trimestre", "Acsa", "8,5"],
        ])

        registros = ler_notas_excel(str(path))
        assert len(registros) == 1
        assert registros[0].data_realizacao == ""

    def test_data_coluna_nao_cria_nota_fantasma(self, tmp_path):
        from datetime import datetime
        from leitor_planilhas import ler_notas_excel

        path = tmp_path / "notas.xlsx"
        _monta_xlsx(path, [
            "Escola", "Turno", "Turma", "Trimestre", "Nome do Aluno",
            "5 - Aula prática", "Data realização 1",
        ], [
            ["Juvenal", "Matutino", "6º Ano", "2º Trimestre", "Acsa",
             "8,5", datetime(2026, 7, 6)],
        ])

        registros = ler_notas_excel(str(path))
        assert len(registros) == 1


class TestLeitorDatasCsv:
    def test_csv_com_datas(self, tmp_path):
        from leitor_planilhas import ler_notas_csv

        path = tmp_path / "notas.csv"
        path.write_text(
            "Escola;Turno;Turma;Trimestre;Nome do Aluno;"
            "5 - Aula prática;Data realização 1;Atividade 2;Atividade 3;"
            "Data realização 2;Data realização 3\n"
            "Juvenal;Matutino;6º Ano;2º Trimestre;Acsa;"
            "8,5;06/07/2026;;;\n",
            encoding="utf-8-sig",
        )

        registros = ler_notas_csv(str(path))
        assert len(registros) == 1
        reg = registros[0]
        assert reg.atividade == "5 - Aula prática"
        assert reg.nota == 8.5
        assert reg.data_realizacao == "06/07/2026"


class TestFormatDataRealizacao:
    def test_datetime_object(self):
        from datetime import datetime
        from leitor_planilhas import _format_data_realizacao
        assert _format_data_realizacao(datetime(2026, 7, 6, 0, 0)) == "06/07/2026"

    def test_string_dd_mm_yyyy(self):
        from leitor_planilhas import _format_data_realizacao
        assert _format_data_realizacao("06/07/2026") == "06/07/2026"

    def test_string_iso(self):
        from leitor_planilhas import _format_data_realizacao
        assert _format_data_realizacao("2026-07-06") == "06/07/2026"

    def test_string_invalida_retorna_original(self):
        from leitor_planilhas import _format_data_realizacao
        assert _format_data_realizacao("nao informado") == "nao informado"

    def test_none_ou_vazio(self):
        from leitor_planilhas import _format_data_realizacao
        assert _format_data_realizacao(None) == ""
        assert _format_data_realizacao("") == ""


class TestPairDateColumns:
    def test_associacao_por_posicao(self):
        from leitor_planilhas import _pair_date_columns
        activities = [(5, "5 - Aula prática"), (7, "Atividade 2"), (8, "Atividade 3")]
        dates = [
            (6, "Data realização 1", 1),
            (9, "Data realização 2", 2),
            (10, "Data realização 3", 3),
        ]
        mapping = _pair_date_columns(activities, dates)
        assert mapping[5] == 6
        assert mapping[7] == 9
        assert mapping[8] == 10

    def test_associacao_por_numero_no_nome(self):
        from leitor_planilhas import _pair_date_columns
        activities = [(5, "Atividade 2"), (6, "Atividade 1")]
        dates = [(7, "Data realização 1", 1), (8, "Data realização 2", 2)]
        mapping = _pair_date_columns(activities, dates)
        assert mapping[6] == 7
        assert mapping[5] == 8

    def test_datas_sem_sufixo(self):
        from leitor_planilhas import _pair_date_columns
        activities = [(5, "Atividade 1"), (6, "Atividade 2")]
        dates = [(7, "Data realização", None)]
        mapping = _pair_date_columns(activities, dates)
        assert len(mapping) == 1
        assert mapping[5] == 7
