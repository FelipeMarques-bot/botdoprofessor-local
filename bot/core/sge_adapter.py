import re
from typing import Optional, List, Dict
from bot.core.portal_adapter import PortalAdapter, PortalContext, StudentGrade
from bot.core.portal_memory import PortalMemory

try:
    from playwright.sync_api import sync_playwright, Page, Browser
except ImportError:
    sync_playwright = None


class SGEAdapter(PortalAdapter):
    """Adapter para o sistema SGE (sge8147.com.br e similares)."""

    NAV_TIMEOUT = 20000
    ACTION_TIMEOUT = 5000

    def __init__(self, base_url: str = ""):
        self._base_url = base_url or "https://www.sge8147.com.br"
        self._page: Optional[Page] = None
        self._browser: Optional[Browser] = None
        self._pw = None
        self.memory = PortalMemory("SGE")
        self._logged_in = False
        self._current_url = ""

    @property
    def name(self) -> str:
        return "SGE"

    @property
    def url(self) -> str:
        return self._base_url

    def start(self):
        if sync_playwright is None:
            raise RuntimeError("Playwright nao instalado")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self.NAV_TIMEOUT)

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    @property
    def page(self) -> Page:
        if not self._page:
            self.start()
        return self._page

    def login(self, cpf: str, senha: str) -> bool:
        p = self.page
        urls_to_try = [
            f"{self._base_url}/hportalprofessor.aspx",
            f"{self._base_url}/hPortalProfessor8147.aspx",
            self._base_url,
        ]
        for url in urls_to_try:
            try:
                p.goto(url, timeout=self.NAV_TIMEOUT, wait_until="domcontentloaded")
                if self._detect_login_form(p):
                    return self._do_login(p, cpf, senha)
            except Exception:
                continue
        return self._logged_in

    def _detect_login_form(self, page: Page) -> bool:
        selectors = [
            "input[name*='cpf' i]", "input[id*='cpf' i]",
            "input[name*='usuario' i]", "input[id*='usuario' i]",
            "#_USUCOD", "input[name='_USUCOD']",
        ]
        for sel in selectors:
            if page.locator(sel).count() > 0:
                return True
        return False

    def _do_login(self, page: Page, cpf: str, senha: str) -> bool:
        cpf_selectors = [
            "input[name*='cpf' i]", "input[id*='cpf' i]",
            "#_USUCOD", "input[name='_USUCOD']",
        ]
        for sel in cpf_selectors:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.fill(cpf)
                break

        senha_selectors = [
            "input[type='password']", "input[name*='senha' i]",
            "input[id*='senha' i]",
        ]
        for sel in senha_selectors:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.fill(senha)
                break

        btn_selectors = [
            "input[type='submit']", "button[type='submit']",
            "input[value*='Entrar' i]", "input[value*='Acessar' i]",
            "a[id*='entrar' i]", "a[id*='acessar' i]",
        ]
        for sel in btn_selectors:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=self.ACTION_TIMEOUT)
                break

        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        self._logged_in = self._detect_dashboard(page)
        if self._logged_in:
            self.memory.record_success("login", self._base_url)
        else:
            self.memory.record_failure("login", self._base_url, "Dashboard nao detectado")
        return self._logged_in

    def _detect_dashboard(self, page: Page) -> bool:
        indicators = ["dashboard", "portal", "professor", "boletim"]
        url = page.url.lower()
        return any(ind in url for ind in indicators)

    def navigate_to(self, context: PortalContext) -> bool:
        """Navega ate o contexto (escola/turno/turma/trimestre)."""
        p = self.page
        selectors = {
            "escola": f"select option:text-is('{context.escola}')",
            "turno": f"select option:text-is('{context.turno}')",
            "turma": f"select option:text-is('{context.turma}')",
            "trimestre": f"select option:text-is('{context.trimestre}')",
        }
        for field_name, sel in selectors.items():
            try:
                dropdown = p.locator("select").filter(has_text=getattr(context, field_name, ""))
                if dropdown.count() > 0:
                    dropdown.first.select_option(label=getattr(context, field_name, ""))
            except Exception:
                pass

        try:
            p.wait_for_timeout(2000)
        except Exception:
            pass

        self.memory.record_navigation(
            f"{context.escola}/{context.turno}/{context.turma}",
            p.url,
        )
        return True

    def find_assessment(self, atividade: str) -> Optional[Dict]:
        p = self.page
        try:
            links = p.locator("a")
            count = links.count()
            for i in range(count):
                text = links.nth(i).text_content() or ""
                if atividade.lower() in text.lower():
                    links.nth(i).click(timeout=self.ACTION_TIMEOUT)
                    return {"found": True, "text": text.strip()}
        except Exception as e:
            self.memory.record_failure("find_assessment", atividade, str(e))
        return None

    def detect_columns(self) -> Dict[str, str]:
        p = self.page
        result = {}
        try:
            inputs = p.evaluate("""
                () => Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'))
                    .map(el => ({ name: el.name || '', id: el.id || '' }))
            """)
            pattern = re.compile(r"(?:^|[_.])(N\d+S|NOTA\s*\d+|PE)(?:[_\s]|$)", re.I)
            counts = {}
            for inp in inputs:
                attrs = f"{inp['name']} {inp['id']}"
                m = pattern.search(attrs)
                if m:
                    col = m.group(1).upper()
                    counts[col] = counts.get(col, 0) + 1
            if counts:
                sorted_cols = sorted(counts.items(), key=lambda x: x[1], reverse=True)
                for i, (col, _) in enumerate(sorted_cols, 1):
                    result[str(i)] = col
                    self.memory.record_column(i, col)
        except Exception:
            pass
        return result

    def read_grades(self) -> List[Dict]:
        p = self.page
        grades = []
        try:
            slots = p.evaluate(r"""
                () => {
                    const out = [];
                    const seen = new Set();
                    const els = document.querySelectorAll(
                        "input[name^='_ALUMATNOM_'], span[id^='span__ALUMATNOM_']"
                    );
                    for (const el of els) {
                        const attr = (el.getAttribute('name') || el.getAttribute('id') || '');
                        const m = attr.match(/_ALUMATNOM_(\d{4})$/);
                        if (!m) continue;
                        const suffix = m[1];
                        if (seen.has(suffix)) continue;
                        seen.add(suffix);
                        const raw = (el.value ?? el.textContent ?? '').trim();
                        if (raw) out.push({ suffix, aluno: raw });
                    }
                    return out;
                }
            """)
            for slot in (slots or []):
                suffix = slot.get("suffix", "")
                aluno = slot.get("aluno", "")
                nota = ""
                try:
                    nota_val = p.evaluate("""
                        (suffix) => {
                            const els = document.querySelectorAll('input[type="text"], input[type="number"]');
                            for (const el of els) {
                                const attrs = (el.name + ' ' + el.id).toLowerCase();
                                if (attrs.includes('_' + suffix)) {
                                    return el.value || '';
                                }
                            }
                            return '';
                        }
                    """, suffix)
                    nota = str(nota_val or "").strip()
                except Exception:
                    pass
                grades.append({"aluno": aluno, "suffix": suffix, "nota": nota})
        except Exception:
            pass
        return grades

    def fill_grade(self, aluno: str, nota: str, coluna: str = "") -> bool:
        p = self.page
        try:
            slots = p.evaluate(r"""
                () => {
                    const out = [];
                    const seen = new Set();
                    const els = document.querySelectorAll(
                        "input[name^='_ALUMATNOM_'], span[id^='span__ALUMATNOM_']"
                    );
                    for (const el of els) {
                        const attr = (el.getAttribute('name') || el.getAttribute('id') || '');
                        const m = attr.match(/_ALUMATNOM_(\d{4})$/);
                        if (!m) continue;
                        const suffix = m[1];
                        if (seen.has(suffix)) continue;
                        seen.add(suffix);
                        const raw = (el.value ?? el.textContent ?? '').trim();
                        if (raw) out.push({ suffix, aluno: raw });
                    }
                    return out;
                }
            """)
            best_suffix = None
            best_score = 0
            for slot in (slots or []):
                slot_aluno = slot.get("aluno", "")
                score = self._name_similarity(aluno, slot_aluno)
                if score > best_score:
                    best_score = score
                    best_suffix = slot.get("suffix")

            if not best_suffix:
                self.memory.record_failure("fill_grade", aluno, "Suffix nao encontrado")
                return False

            result = p.evaluate("""
                ({suffix, nota, coluna}) => {
                    const els = document.querySelectorAll('input[type="text"], input[type="number"]');
                    for (const el of els) {
                        const id = (el.id || '').trim();
                        if (id && id.toLowerCase().includes('_' + suffix.toLowerCase())) {
                            if (coluna && !id.toLowerCase().includes('_' + coluna.toLowerCase() + '_'))
                                continue;
                            el.value = nota;
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                            return 'filled';
                        }
                    }
                    for (const el of els) {
                        const name = (el.name || '').trim();
                        if (name && name.toLowerCase().includes('_' + suffix.toLowerCase())) {
                            if (coluna && !name.toLowerCase().includes('_' + coluna.toLowerCase() + '_'))
                                continue;
                            el.value = nota;
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                            return 'filled';
                        }
                    }
                    return 'not_found';
                }
            """, {"suffix": best_suffix, "nota": nota, "coluna": coluna})

            if result == "filled":
                self.memory.record_success("fill_grade", f"suffix={best_suffix}")
                return True
            else:
                self.memory.record_failure("fill_grade", aluno, f"result={result}")
                return False
        except Exception as e:
            self.memory.record_failure("fill_grade", aluno, str(e))
            return False

    def save(self) -> bool:
        p = self.page
        try:
            save_selectors = [
                "input[value*='Salvar' i]", "button:has-text('Salvar')",
                "input[type='submit'][value*='Salvar' i]",
                "#btnSalvar", "a[id*='salvar' i]",
            ]
            for sel in save_selectors:
                loc = p.locator(sel)
                if loc.count() > 0:
                    loc.first.click(timeout=self.ACTION_TIMEOUT)
                    try:
                        p.wait_for_timeout(2000)
                    except Exception:
                        pass
                    self.memory.record_success("save", sel)
                    return True
            self.memory.record_failure("save", "no_button", "Botao de salvar nao encontrado")
            return False
        except Exception as e:
            self.memory.record_failure("save", "error", str(e))
            return False

    def is_logged_in(self) -> bool:
        return self._logged_in

    def get_student_sample(self, limit: int = 10) -> List[str]:
        p = self.page
        sample = []
        try:
            els = p.evaluate("""
                (limit) => {
                    const out = [];
                    const els = document.querySelectorAll(
                        "input[name^='_ALUMATNOM_'], span[id^='span__ALUMATNOM_']"
                    );
                    for (const el of els) {
                        const raw = (el.value ?? el.textContent ?? '').trim();
                        if (raw) out.push(raw);
                        if (out.length >= limit) break;
                    }
                    return out;
                }
            """, limit)
            sample = els or []
        except Exception:
            pass
        return sample

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
        intersection = a_tokens & b_tokens
        return len(intersection) / max(len(a_tokens), len(b_tokens))
