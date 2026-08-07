class FakeLocator:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class FakePage:
    def __init__(self, url="", present=()):
        self.url = url
        self._present = set(present)

    def locator(self, selector):
        return FakeLocator(1 if selector in self._present else 0)

    def get_by_text(self, text, exact=False):
        return FakeLocator(1 if "Professor" in text else 0)


class TestIsLoginPage:
    def test_por_url_hlogin(self):
        from lancar_notas_sge import _is_login_page

        page = FakePage(url="https://www.sge8147.com.br/hlogin8147.aspx")
        assert _is_login_page(page) is True

    def test_por_usucod(self):
        from lancar_notas_sge import _is_login_page

        page = FakePage(present=("input[name='_USUCOD']",))
        assert _is_login_page(page) is True

    def test_por_formulario_sge_nmrcpfsrv(self):
        from lancar_notas_sge import _is_login_page

        page = FakePage(present=("input[name='_NMRCPFSRV']",))
        assert _is_login_page(page) is True

    def test_por_formulario_sge_senhawed(self):
        from lancar_notas_sge import _is_login_page

        page = FakePage(present=("input[name='_SENHAWEB']",))
        assert _is_login_page(page) is True

    def test_dashboard_nao_e_login(self):
        from lancar_notas_sge import _is_login_page

        page = FakePage(present=("select[name='W0019_SECNUMFILTRODISC']",))
        assert _is_login_page(page) is False


class TestNormalizeCpf:
    def test_11_digitos_ok(self):
        from lancar_notas_sge import _normalize_cpf_for_sge

        assert _normalize_cpf_for_sge("123.456.789-01") == "12345678901"

    def test_10_digitos_padrao_zero(self):
        from lancar_notas_sge import _normalize_cpf_for_sge

        assert _normalize_cpf_for_sge("9748010001") == "09748010001"

    def test_digitos_invalidos_levanta(self):
        from lancar_notas_sge import LancamentoError, _normalize_cpf_for_sge

        try:
            _normalize_cpf_for_sge("99748010")
        except LancamentoError:
            return
        raise AssertionError("CPF com 8 digitos deveria levantar LancamentoError")


class TestIsDashboardPage:
    def test_login_nao_e_dashboard(self):
        from lancar_notas_sge import _is_dashboard_page

        page = FakePage(
            url="https://www.sge8147.com.br/hportalprofessor.aspx",
            present=("input[name='_NMRCPFSRV']", "input[name='_SENHAWEB']"),
        )
        assert _is_dashboard_page(page) is False

    def test_portal_professor_texto_sozinho_e_dashboard_fallback(self):
        from lancar_notas_sge import _is_dashboard_page

        page = FakePage(url="https://www.sge8147.com.br/hportalprofessor.aspx")
        assert _is_dashboard_page(page) is True

    def test_dashboard_com_w0019(self):
        from lancar_notas_sge import _is_dashboard_page

        page = FakePage(present=("select[name='W0019_SECNUMFILTRODISC']",))
        assert _is_dashboard_page(page) is True
