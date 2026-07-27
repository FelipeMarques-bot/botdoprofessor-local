import re
import os
import tempfile
import urllib.request
from typing import Optional, List, Dict
from bot.core.portal_adapter import (
    PortalAdapter, PortalContext, StudentGrade, LessonPlan, LessonPlanResult,
)
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
            ai_result = self._ai_analyze_failure("login", "Dashboard nao detectado", f"url={self._base_url}")
            if ai_result and ai_result.get("suggested_fixes"):
                for fix in ai_result["suggested_fixes"]:
                    sel = fix.get("selector", "")
                    if sel:
                        try:
                            page.locator(sel).first.click(timeout=5000)
                            page.wait_for_load_state("networkidle", timeout=10000)
                            self._logged_in = self._detect_dashboard(page)
                            if self._logged_in:
                                self.memory.record_success("login", f"ai_fix={sel}")
                                return True
                        except Exception:
                            continue
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
                return self._try_fill_with_ai(aluno, nota, coluna)
        except Exception as e:
            self.memory.record_failure("fill_grade", aluno, str(e))
            return self._try_fill_with_ai(aluno, nota, coluna)

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
            alt_sel = self._ai_adapt_selector("Salvar", "click", "Botao nao encontrado")
            if alt_sel:
                try:
                    p.locator(alt_sel).first.click(timeout=self.ACTION_TIMEOUT)
                    p.wait_for_timeout(2000)
                    self.memory.record_success("save", f"ai_selector={alt_sel}")
                    return True
                except Exception:
                    pass
            return False
        except Exception as e:
            self.memory.record_failure("save", "error", str(e))
            alt_sel = self._ai_adapt_selector("Salvar", "click", str(e))
            if alt_sel:
                try:
                    p.locator(alt_sel).first.click(timeout=self.ACTION_TIMEOUT)
                    p.wait_for_timeout(2000)
                    self.memory.record_success("save", f"ai_selector={alt_sel}")
                    return True
                except Exception:
                    pass
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

    # ------------------------------------------------------------------ #
    #  Reforco IA — Fallback automatico quando operacoes falham           #
    # ------------------------------------------------------------------ #

    def _take_screenshot(self) -> Optional[bytes]:
        """Tira screenshot da pagina atual para analise da IA."""
        try:
            if self._page:
                return self._page.screenshot()
        except Exception:
            pass
        return None

    def _ai_analyze_failure(self, operation: str, error: str, context: str = "") -> Optional[Dict]:
        """Usa IA para analisar uma falha e sugerir correcao."""
        try:
            from ai_assist import is_available, analyze_portal_failure
            if not is_available():
                return None
            screenshot = self._take_screenshot()
            if not screenshot:
                return None
            return analyze_portal_failure(
                screenshot, error, operation, context, logger=None
            )
        except ImportError:
            return None

    def _ai_adapt_selector(self, original_selector: str, action: str, error: str) -> Optional[str]:
        """Usa IA para encontrar um selector alternativo quando o original falha."""
        try:
            from ai_assist import is_available, adapt_selector
            if not is_available():
                return None
            screenshot = self._take_screenshot()
            if not screenshot:
                return None
            result = adapt_selector(original_selector, action, error, screenshot, logger=None)
            alternatives = result.get("alternatives", [])
            for alt in alternatives:
                sel = alt.get("selector", "")
                if sel:
                    return sel
        except ImportError:
            pass
        return None

    def _ai_discover_portal(self) -> Optional[Dict]:
        """Usa IA para redescobrir a estrutura do portal a partir do screenshot."""
        try:
            from ai_assist import is_available, discover_portal_from_screenshot
            if not is_available():
                return None
            screenshot = self._take_screenshot()
            if not screenshot:
                return None
            return discover_portal_from_screenshot(screenshot, logger=None)
        except ImportError:
            return None

    def _try_fill_with_ai(self, aluno: str, nota: str, coluna: str = "") -> bool:
        """Fallback: quando fill_grade falha, IA tenta encontrar o input correto."""
        try:
            from ai_assist import is_available, adapt_selector
            if not is_available():
                return False
            screenshot = self._take_screenshot()
            if not screenshot:
                return False
            result = adapt_selector(
                "_ALUMATNOM_", "fill",
                f"Aluno '{aluno}' nao encontrado na grade",
                screenshot, logger=None
            )
            for alt in result.get("alternatives", []):
                sel = alt.get("selector", "")
                if not sel:
                    continue
                try:
                    p = self.page
                    loc = p.locator(sel)
                    if loc.count() > 0:
                        for i in range(loc.count()):
                            text = loc.nth(i).text_content() or ""
                            if self._name_similarity(aluno, text.strip()) > 0.5:
                                input_sel = alt.get("selector", "").replace("text", "input")
                                input_loc = p.locator(input_sel)
                                if input_loc.count() > i:
                                    input_loc.nth(i).fill(nota)
                                    self.memory.record_success("fill_grade", f"ai_selector={sel}")
                                    return True
                except Exception:
                    continue
        except ImportError:
            pass
        return False

    # ------------------------------------------------------------------ #
    #  Helpers internos — Plano de Aula                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

    @staticmethod
    def _extract_turma_number(turma: str) -> str:
        m = re.search(r"(\d+)", turma or "")
        return m.group(1) if m else ""

    @staticmethod
    def _extract_first_number(text: str) -> str:
        m = re.search(r"(\d+)", text or "")
        return m.group(1) if m else ""

    def _iter_scopes(self, page: Page):
        """Yield locators for main content, iframe, and shadow roots."""
        yield page
        for frame in page.frames:
            if frame != page.main_frame:
                yield frame

    def _click_text_any_scope(self, page: Page, text: str) -> bool:
        for scope in self._iter_scopes(page):
            for tag in ["a", "input", "button", "span", "td"]:
                loc = scope.locator(f"{tag}:has-text('{text}')")
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=self.ACTION_TIMEOUT)
                        return True
                    except Exception:
                        continue
        return False

    def _click_any_selector(self, page: Page, selectors: list) -> bool:
        for scope in self._iter_scopes(page):
            for sel in selectors:
                try:
                    loc = scope.locator(sel)
                    if loc.count() == 0:
                        continue
                    loc.first.click(timeout=self.ACTION_TIMEOUT)
                    return True
                except Exception:
                    continue
        return False

    def _set_filters_on_portal(self, page: Page, context: PortalContext) -> None:
        for scope in self._iter_scopes(page):
            for dropdown in scope.locator("select").all():
                try:
                    text = dropdown.inner_text(timeout=300)
                    norm = self._normalize(text)
                    if context.turno and self._normalize(context.turno) in norm:
                        for opt in dropdown.locator("option").all():
                            if self._normalize(context.turno) in self._normalize(opt.inner_text(timeout=200)):
                                dropdown.select_option(value=opt.get_attribute("value"))
                                break
                    elif context.turma and self._normalize(context.turma) in norm:
                        for opt in dropdown.locator("option").all():
                            if self._normalize(context.turma) in self._normalize(opt.inner_text(timeout=200)):
                                dropdown.select_option(value=opt.get_attribute("value"))
                                break
                except Exception:
                    continue
        try:
            page.wait_for_timeout(1500)
        except Exception:
            pass

    def _click_cell_action_by_header(self, row, header_key: str, prefer_arrow: bool = False) -> bool:
        js = """
        ({ key, preferArrow }) => {
            const tr = rowEl;
            const table = tr.closest('table');
            if (!table) return false;
            const normalize = (s) => (s || '').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').trim();
            const keyNorm = normalize(key);
            const headerRow = Array.from(table.querySelectorAll('tr')).find((r) => {
                const text = normalize(r.textContent || '');
                return text.includes('periodo') && text.includes('situacao');
            });
            if (!headerRow) return false;
            const heads = Array.from(headerRow.querySelectorAll('th, td'));
            let colIdx = -1;
            for (let i = 0; i < heads.length; i++) {
                const h = normalize(heads[i].textContent || '');
                if (h.includes(keyNorm)) { colIdx = i; break; }
            }
            if (colIdx < 0) return false;
            const cells = Array.from(tr.querySelectorAll('td, th'));
            if (colIdx >= cells.length) return false;
            const cell = cells[colIdx];
            const clickables = Array.from(cell.querySelectorAll('a, input[type="image"], button, img'));
            if (!clickables.length) return false;
            const meta = (el) => normalize([
                el.getAttribute?.('title') || '', el.getAttribute?.('alt') || '',
                el.getAttribute?.('name') || '', el.getAttribute?.('id') || '',
                el.getAttribute?.('src') || '',
            ].join(' '));
            let target = null;
            if (preferArrow) {
                target = clickables.find((el) => {
                    const m = meta(el);
                    return m.includes('seta') || m.includes('arrow') || m.includes('direita') || m.includes('status') || m.includes('situ');
                });
            }
            if (!target) target = clickables.find((el) => meta(el).includes(keyNorm));
            if (!target) target = clickables[0];
            const clickable = target.closest?.('a, button, input[type="image"]') || target;
            clickable.click();
            return true;
        }
        """
        try:
            return bool(row.evaluate(
                js.replace("rowEl", "el"),
                {"key": header_key, "preferArrow": prefer_arrow},
            ))
        except Exception:
            return False

    def _row_for_periodo(self, page: Page, data_inicio: str, data_fim: str):
        dd_i = data_inicio[:5]
        dd_f = data_fim[:5]
        for scope in self._iter_scopes(page):
            try:
                grid = scope.locator("table[id='GRIDPLANEJADO']")
                if grid.count() == 0:
                    continue
                rows = grid.locator("> tbody > tr")
                total = rows.count()
            except Exception:
                continue
            for idx in range(total):
                row = rows.nth(idx)
                try:
                    text = self._normalize(row.inner_text(timeout=300))
                except Exception:
                    continue
                if not text or "periodo" in text or "situacao" in text:
                    continue
                if dd_i in text and dd_f in text:
                    return row
        return None

    def _click_anexo_icon_on_row(self, row) -> bool:
        if self._click_cell_action_by_header(row, "anex", prefer_arrow=False):
            return True
        try:
            icons = row.locator("a, img, input[type='image']")
            total = icons.count()
        except Exception:
            return False
        for idx in range(total):
            node = icons.nth(idx)
            try:
                meta = " ".join([
                    (node.get_attribute("title") or ""),
                    (node.get_attribute("alt") or ""),
                    (node.get_attribute("src") or ""),
                    (node.get_attribute("name") or ""),
                ])
                if "anex" not in self._normalize(meta):
                    continue
                node.click(timeout=self.ACTION_TIMEOUT)
                return True
            except Exception:
                continue
        return False

    def _ativar_situacao_da_linha(self, row) -> bool:
        if self._click_cell_action_by_header(row, "situ", prefer_arrow=True):
            return True
        try:
            icons = row.locator("a, img, input[type='image']")
            total = icons.count()
        except Exception:
            return False
        for idx in range(total):
            node = icons.nth(idx)
            try:
                meta = " ".join([
                    (node.get_attribute("title") or ""),
                    (node.get_attribute("alt") or ""),
                    (node.get_attribute("src") or ""),
                    (node.get_attribute("name") or ""),
                ])
                norm = self._normalize(meta)
                if "situ" in norm or "seta" in norm or "status" in norm:
                    node.click(timeout=self.ACTION_TIMEOUT)
                    return True
            except Exception:
                continue
        if total > 0:
            try:
                icons.nth(total - 1).click(timeout=self.ACTION_TIMEOUT)
                return True
            except Exception:
                return False
        return False

    def _click_plus_planejamento(self, page: Page) -> bool:
        js = """
        () => {
            const incluir = document.querySelector('a[onclick*="INCLUIRPLANEJAMENTO" i]');
            if (incluir) { incluir.click(); return true; }
            const txt = Array.from(document.querySelectorAll('body *')).find((el) => {
                const t = (el.textContent || '').toLowerCase();
                return t.includes('planejamentos:');
            });
            if (!txt) return false;
            const root = txt.closest('table, div, tr, td') || txt.parentElement || document.body;
            const candidate = root.querySelector(
                'img[alt="+"]' + ', input[type="image"][alt="+"]' + ', a img[alt="+"]'
                + ', img[src*="plus" i]' + ', img[src*="mais" i]'
                + ', button, a, input[type="submit"], input[type="button"]'
            );
            if (!candidate) return false;
            if (['A', 'BUTTON', 'INPUT'].includes(candidate.tagName)) {
                candidate.click();
            } else {
                const clickable = candidate.closest('a, button, input[type="image"]') || candidate;
                clickable.click();
            }
            return true;
        }
        """
        try:
            if page.evaluate(js):
                return True
        except Exception:
            pass
        return self._click_any_selector(page, [
            "a[onclick*='INCLUIRPLANEJAMENTO' i]",
            "a:has(img[name='INCLUI'])",
            "img[name='INCLUI']",
            "img[alt='+']",
            "input[type='image'][alt='+']",
            "a:has(img[alt='+'])",
            "img[src*='plus' i]",
            "img[src*='mais' i]",
            "button:has-text('+')",
            "a:has-text('+')",
        ])

    def _set_periodo_and_aulas(self, page: Page, data_inicio: str, data_fim: str, n_aulas: int) -> bool:
        try:
            page.locator("input[name='_PLAULADTINICIO']").fill(data_inicio, timeout=self.ACTION_TIMEOUT)
            page.locator("input[name='_PLAULADTFIM']").fill(data_fim, timeout=self.ACTION_TIMEOUT)
            page.locator("input[name='_PLAULANUMAULAS']").fill(str(int(n_aulas)), timeout=self.ACTION_TIMEOUT)
            page.wait_for_timeout(500)
            return True
        except Exception:
            pass
        js = """
        ({ inicio, fim, aulas }) => {
          const allText = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'))
            .filter((el) => !el.disabled && !el.readOnly);
          const isDateLike = (el) => {
            const key = `${el.name || ''} ${el.id || ''}`.toLowerCase();
            return key.includes('period') || key.includes('data') || key.includes('dt');
          };
          let dateInputs = allText.filter(isDateLike);
          if (dateInputs.length >= 2) {
            dateInputs[0].value = inicio;
            dateInputs[1].value = fim;
          }
          let aulasInput = allText.find((el) => {
            const key = `${el.name || ''} ${el.id || ''}`.toLowerCase();
            return key.includes('aula');
          });
          if (!aulasInput) {
            aulasInput = allText.find((el) => /^\\d*$/.test((el.value || '').trim())) || null;
          }
          if (!aulasInput) return false;
          aulasInput.value = String(aulas);
          return true;
        }
        """
        try:
            return bool(page.evaluate(js, {"inicio": data_inicio, "fim": data_fim, "aulas": int(n_aulas)}))
        except Exception:
            return False

    def _click_confirmar(self, page: Page) -> bool:
        return self._click_any_selector(page, [
            "input[name='BTNCONFIRMAR']",
            "button:has-text('Confirmar')",
            "input[value*='Confirmar' i]",
        ])

    def _download_pdf(self, url: str, name_hint: str) -> str:
        base_name = (name_hint or "plano_aula.pdf").strip()
        if not base_name.lower().endswith(".pdf"):
            base_name = f"{base_name}.pdf"
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", base_name)
        tmp_dir = tempfile.mkdtemp(prefix="plano_aula_")
        target = os.path.join(tmp_dir, safe_name)
        dl_url = url
        m = re.search(r"(?:drive\.google\.com/file/d/|drive\.google\.com/open\?id=|drive\.google\.com/uc\?id=)([a-zA-Z0-9_-]+)", url)
        if m:
            dl_url = f"https://drive.google.com/uc?export=download&id={m.group(1)}"
        req = urllib.request.Request(dl_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read()
        with open(target, "wb") as f:
            f.write(data)
        return target

    def _fill_anexo_form(self, page: Page, titulo_documento: str, arquivo_path: str) -> bool:
        ok_doc = False
        for scope in self._iter_scopes(page):
            for sel in [
                "input[name*='ARQNOM' i]", "input[name*='DOCOBS' i]",
                "input[id*='ARQNOM' i]", "input[name*='PLAULA' i][type='text']",
                "input[type='text']",
            ]:
                try:
                    loc = scope.locator(sel)
                    if loc.count() == 0:
                        continue
                    loc.first.fill(titulo_documento, timeout=self.ACTION_TIMEOUT)
                    ok_doc = True
                    break
                except Exception:
                    continue
            if ok_doc:
                break

        tipo_set = False
        for scope in self._iter_scopes(page):
            try:
                selects = scope.locator("select")
                total = selects.count()
            except Exception:
                continue
            for i in range(total):
                sel = selects.nth(i)
                try:
                    options = sel.locator("option")
                    ocount = options.count()
                except Exception:
                    continue
                target_value = None
                for j in range(ocount):
                    try:
                        label = (options.nth(j).inner_text(timeout=200) or "").strip()
                    except Exception:
                        continue
                    if "detal" in self._normalize(label) or "descricao" in self._normalize(label) or "anexo" in self._normalize(label):
                        target_value = options.nth(j).get_attribute("value")
                        break
                if target_value is not None:
                    try:
                        sel.select_option(value=target_value)
                        tipo_set = True
                        break
                    except Exception:
                        continue
            if tipo_set:
                break

        file_set = False
        for scope in self._iter_scopes(page):
            try:
                file_loc = scope.locator("input[type='file']")
                if file_loc.count() > 0:
                    file_loc.first.set_input_files(arquivo_path)
                    file_set = True
                    break
            except Exception:
                continue

        return ok_doc and tipo_set and file_set

    # ------------------------------------------------------------------ #
    #  API pública — Plano de Aula                                         #
    # ------------------------------------------------------------------ #

    def supports_lesson_plan(self) -> bool:
        return True

    def navigate_to_lesson_plan(self, context: PortalContext) -> bool:
        p = self.page
        try:
            p.goto(
                f"{self._base_url}/hportalprofessor.aspx",
                wait_until="domcontentloaded", timeout=self.NAV_TIMEOUT,
            )
        except Exception:
            pass
        try:
            p.wait_for_load_state("networkidle", timeout=self.NAV_TIMEOUT)
        except Exception:
            pass
        try:
            p.wait_for_timeout(1500)
        except Exception:
            pass

        escola_ok = False
        for _ in range(5):
            try:
                p.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            try:
                p.wait_for_timeout(1000)
            except Exception:
                pass
            if self._click_text_any_scope(p, context.escola):
                escola_ok = True
                break
        if not escola_ok:
            return False
        try:
            p.wait_for_load_state("networkidle", timeout=self.NAV_TIMEOUT)
        except Exception:
            pass
        try:
            p.wait_for_timeout(2000)
        except Exception:
            pass

        turma_num = self._extract_turma_number(context.turma)
        trimestre_num = self._extract_first_number(context.trimestre)
        turno_norm = self._normalize(context.turno).upper()
        etapa_num = self._extract_first_number(context.turma)

        self._set_filters_on_portal(p, context)
        try:
            p.wait_for_timeout(1500)
        except Exception:
            pass

        for scope in self._iter_scopes(p):
            for attempt in range(10):
                hidden_rows = scope.locator("input[name^='W0019W0075_TURNUMSTR_']")
                total = hidden_rows.count()
                if total > 0:
                    break
                try:
                    p.wait_for_timeout(500)
                except Exception:
                    pass
            else:
                total = 0

            for idx in range(total):
                cell = hidden_rows.nth(idx)
                try:
                    label = (cell.input_value(timeout=400) or "").strip()
                except Exception:
                    continue
                norm = self._normalize(label)
                ok_turno = bool(turno_norm and self._normalize(turno_norm) in norm)
                ok_turma = True if not turma_num else bool(re.search(rf"\bturma\s*{re.escape(turma_num)}\b", norm))
                ok_trim = bool(trimestre_num and f"{trimestre_num}o trimestre" in norm)
                ok_etapa = not bool(etapa_num) or bool(re.search(rf"\b{re.escape(etapa_num)}\s*[ºo]?\s*ano\b", norm))
                if not (ok_turno and ok_turma and ok_trim and ok_etapa):
                    continue

                name = (cell.get_attribute("name") or "")
                suffix = name.rsplit("_", 1)[-1]
                selectors = [
                    f"#W0019W0075_DISCIPLINA_{suffix}",
                    f"img[name='W0019W0075_DISCIPLINA_{suffix}']",
                    f"a:has(img[name='W0019W0075_DISCIPLINA_{suffix}'])",
                    f"#W0019W0075_PLANOAULA_{suffix}",
                    f"img[name='W0019W0075_PLANOAULA_{suffix}']",
                    f"#W0019W0075_PLANODEAULA_{suffix}",
                    f"img[name='W0019W0075_PLANODEAULA_{suffix}']",
                ]
                for sel in selectors:
                    try:
                        icon = scope.locator(sel)
                        if icon.count() == 0:
                            continue
                        icon.first.click(timeout=self.ACTION_TIMEOUT)
                        try:
                            p.wait_for_load_state("networkidle", timeout=self.NAV_TIMEOUT)
                        except Exception:
                            pass
                        try:
                            p.wait_for_timeout(2000)
                        except Exception:
                            pass
                        if "planejamentoaula" in (p.url or "").lower():
                            self.memory.record_success("navigate_to_lesson_plan", context.escola)
                            return True
                    except Exception:
                        continue

        try:
            p.goto(
                f"{self._base_url}/hportalplanejamentoaula.aspx",
                wait_until="domcontentloaded", timeout=self.NAV_TIMEOUT,
            )
            try:
                p.wait_for_timeout(2000)
            except Exception:
                pass
            if "planejamentoaula" in (p.url or "").lower():
                self.memory.record_success("navigate_to_lesson_plan", "fallback_direct")
                return True
        except Exception:
            pass
        self.memory.record_failure("navigate_to_lesson_plan", context.escola, "not_found")
        return False

    def create_lesson_plan(self, plan: LessonPlan) -> bool:
        p = self.page
        if not self._click_plus_planejamento(p):
            return False
        try:
            p.wait_for_load_state("networkidle", timeout=self.NAV_TIMEOUT)
            p.wait_for_timeout(2000)
        except Exception:
            pass
        if not self._set_periodo_and_aulas(p, plan.data_inicio, plan.data_fim, plan.n_aulas):
            return False
        if not self._click_confirmar(p):
            return False
        try:
            p.wait_for_load_state("networkidle", timeout=self.NAV_TIMEOUT)
            p.wait_for_timeout(2500)
        except Exception:
            pass

        form_visivel = False
        try:
            form_visivel = p.locator("table[id='TABDADOSPLANEJAMENTO']").is_visible(timeout=1000)
        except Exception:
            pass
        if form_visivel:
            return False

        self.memory.record_success("create_lesson_plan", plan.titulo)
        return True

    def upload_lesson_plan_pdf(self, titulo: str, pdf_path: str) -> bool:
        p = self.page
        row = None
        for scope in self._iter_scopes(p):
            try:
                grid = scope.locator("table[id='GRIDPLANEJADO']")
                if grid.count() == 0:
                    continue
                rows = grid.locator("> tbody > tr")
                if rows.count() > 0:
                    row = rows.last
                    break
            except Exception:
                continue

        if row is None:
            return False

        if not self._click_anexo_icon_on_row(row):
            return False
        try:
            p.wait_for_load_state("networkidle", timeout=self.NAV_TIMEOUT)
            p.wait_for_timeout(2000)
        except Exception:
            pass

        for scope in self._iter_scopes(p):
            for sel in [
                "a[onclick*='INCLUIRANEXO']",
                "[name='W0260INCLUIANEXO']",
                "[id='W0260INCLUIANEXO']",
                "img[title*='Incluir anexo']",
                "input[type='image'][name*='INCLUIANEXO']",
            ]:
                try:
                    loc = scope.locator(sel)
                    if loc.count() == 0:
                        continue
                    clickable = loc.first
                    a_parent = clickable.locator("xpath=ancestor-or-self::a[1]")
                    if a_parent.count() > 0:
                        a_parent.first.click(timeout=self.ACTION_TIMEOUT)
                    else:
                        clickable.click(timeout=self.ACTION_TIMEOUT)
                    break
                except Exception:
                    continue
            else:
                continue
            break
        else:
            return False

        try:
            p.wait_for_load_state("networkidle", timeout=self.NAV_TIMEOUT)
            p.wait_for_timeout(1500)
        except Exception:
            pass

        if not self._fill_anexo_form(p, titulo, pdf_path):
            return False
        if not self._click_confirmar(p):
            return False
        try:
            p.wait_for_load_state("networkidle", timeout=self.NAV_TIMEOUT)
            p.wait_for_timeout(1500)
        except Exception:
            pass

        self._click_text_any_scope(p, "Voltar")
        try:
            p.wait_for_load_state("networkidle", timeout=self.NAV_TIMEOUT)
            p.wait_for_timeout(1500)
        except Exception:
            pass

        self.memory.record_success("upload_lesson_plan_pdf", titulo)
        return True
