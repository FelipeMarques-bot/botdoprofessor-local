from typing import Optional, List, Dict
from bot.core.portal_adapter import PortalAdapter, PortalContext
from bot.core.portal_memory import PortalMemory

try:
    from playwright.sync_api import sync_playwright, Page, Browser
except ImportError:
    sync_playwright = None


class CustomPortalAdapter(PortalAdapter):
    """Adapter generico para portais desconhecidos, usando estrutura JSON descoberta."""

    def __init__(self, portal_name: str, portal_config: dict):
        self._portal_name = portal_name
        self._config = portal_config
        self._page: Optional[Page] = None
        self._browser: Optional[Browser] = None
        self._pw = None
        self.memory = PortalMemory(portal_name)
        self._logged_in = False

    @property
    def name(self) -> str:
        return self._portal_name

    @property
    def url(self) -> str:
        return self._config.get("url", "")

    def start(self):
        if sync_playwright is None:
            raise RuntimeError("Playwright nao instalado")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(20000)

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    @property
    def page(self):
        if not self._page:
            self.start()
        return self._page

    def login(self, cpf: str, senha: str) -> bool:
        p = self.page
        url = self._config.get("url", "")
        if not url:
            return False
        try:
            p.goto(url, timeout=20000, wait_until="domcontentloaded")
        except Exception:
            return False

        login_flow = self._config.get("login_flow", {})
        if not login_flow:
            login_flow = self._config.get("auth_flow", {})

        cpf_field = login_flow.get("cpf_field", login_flow.get("username_field", ""))
        senha_field = login_flow.get("senha_field", login_flow.get("password_field", ""))
        submit = login_flow.get("submit", {})

        try:
            if cpf_field:
                p.locator(cpf_field).first.fill(cpf)
            if senha_field:
                p.locator(senha_field).first.fill(senha)
            if submit.get("selector"):
                p.locator(submit["selector"]).first.click(timeout=5000)
        except Exception as e:
            self.memory.record_failure("login", url, str(e))
            return False

        try:
            p.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        self._logged_in = True
        self.memory.record_success("login", url)
        return True

    def navigate_to(self, context: PortalContext) -> bool:
        nav = self._config.get("navigation", {})
        p = self.page

        for step in nav.get("steps", []):
            try:
                action = step.get("action", "")
                selector = step.get("selector", "")
                value = getattr(context, step.get("field", ""), step.get("value", ""))
                if action == "select" and selector and value:
                    p.locator(selector).first.select_option(label=str(value))
                elif action == "click" and selector:
                    p.locator(selector).first.click(timeout=5000)
                elif action == "fill" and selector and value:
                    p.locator(selector).first.fill(str(value))
                elif action == "wait":
                    p.wait_for_timeout(int(step.get("ms", 2000)))
            except Exception:
                continue
        return True

    def find_assessment(self, atividade: str) -> Optional[Dict]:
        p = self.page
        grade_config = self._config.get("grade_flow", {})
        selector = grade_config.get("assessment_selector", "")
        if not selector:
            return None
        try:
            els = p.locator(selector)
            count = els.count()
            for i in range(count):
                text = els.nth(i).text_content() or ""
                if atividade.lower() in text.lower():
                    els.nth(i).click(timeout=5000)
                    return {"found": True, "text": text.strip()}
        except Exception:
            pass
        return None

    def detect_columns(self) -> Dict[str, str]:
        return self._config.get("columns", {})

    def read_grades(self) -> List[Dict]:
        p = self.page
        grade_config = self._config.get("grade_flow", {})
        student_selector = grade_config.get("student_name_selector", "")
        grade_inputs = grade_config.get("grade_input_selector", "")
        if not student_selector:
            return []
        grades = []
        try:
            students = p.locator(student_selector)
            count = students.count()
            for i in range(count):
                name = students.nth(i).text_content() or ""
                name = name.strip()
                if not name:
                    continue
                grade = ""
                if grade_inputs:
                    input_els = p.locator(grade_inputs)
                    if input_els.count() > i:
                        grade = input_els.nth(i).input_value() or ""
                grades.append({"aluno": name, "nota": grade.strip()})
        except Exception:
            pass
        return grades

    def fill_grade(self, aluno: str, nota: str, coluna: str = "") -> bool:
        p = self.page
        grade_config = self._config.get("grade_flow", {})
        student_selector = grade_config.get("student_name_selector", "")
        grade_inputs = grade_config.get("grade_input_selector", "")
        if not student_selector or not grade_inputs:
            return False
        try:
            students = p.locator(student_selector)
            count = students.count()
            inputs = p.locator(grade_inputs)
            for i in range(count):
                name = students.nth(i).text_content() or ""
                if self._name_similarity(aluno, name.strip()) > 0.6:
                    if inputs.count() > i:
                        inputs.nth(i).fill(nota)
                        return True
        except Exception as e:
            self.memory.record_failure("fill_grade", aluno, str(e))
        return False

    def save(self) -> bool:
        p = self.page
        save_sel = self._config.get("grade_flow", {}).get("save_selector", "")
        if not save_sel:
            save_sel = "input[value*='Salvar' i], button:has-text('Salvar')"
        try:
            loc = p.locator(save_sel)
            if loc.count() > 0:
                loc.first.click(timeout=5000)
                p.wait_for_timeout(2000)
                self.memory.record_success("save", save_sel)
                return True
        except Exception as e:
            self.memory.record_failure("save", save_sel, str(e))
        return False

    def is_logged_in(self) -> bool:
        return self._logged_in

    @staticmethod
    def _name_similarity(a: str, b: str) -> float:
        a_norm = a.strip().lower()
        b_norm = b.strip().lower()
        if a_norm == b_norm:
            return 1.0
        a_tokens = set(a_norm.split())
        b_tokens = set(b_norm.split())
        if not a_tokens or not b_tokens:
            return 0.0
        return len(a_tokens & b_tokens) / max(len(a_tokens), len(b_tokens))
