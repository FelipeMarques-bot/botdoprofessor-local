from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class StudentGrade:
    aluno: str
    nota: str
    atividade: str = ""
    coluna: str = ""
    data: str = ""


@dataclass
class PortalContext:
    escola: str = ""
    turno: str = ""
    turma: str = ""
    trimestre: str = ""
    atividade: str = ""
    data_realizacao: str = ""


@dataclass
class GradeResult:
    success: bool
    message: str = ""
    filled: int = 0
    failed: int = 0
    skipped: int = 0
    already_exists: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class LessonPlan:
    titulo: str
    data_inicio: str
    data_fim: str
    n_aulas: int
    pdf_path: str = ""
    pdf_url: str = ""


@dataclass
class LessonPlanResult:
    success: bool
    message: str = ""
    planejamento_criado: bool = False
    anexo_enviado: bool = False
    situacao_ativada: bool = False


class PortalAdapter(ABC):
    """Interface abstrata que todo portal de professores deve implementar."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome do portal (ex: 'SGE', 'SGP', 'ieducar')."""
        ...

    @property
    @abstractmethod
    def url(self) -> str:
        """URL base do portal."""
        ...

    @abstractmethod
    def login(self, cpf: str, senha: str) -> bool:
        """Realiza login no portal. Retorna True se sucesso."""
        ...

    @abstractmethod
    def navigate_to(self, context: PortalContext) -> bool:
        """Navega ate o contexto escolhido (escola/turno/turma/trimestre)."""
        ...

    @abstractmethod
    def find_assessment(self, atividade: str) -> Optional[Dict]:
        """Busca e seleciona uma avaliacao/atividade na grade."""
        ...

    @abstractmethod
    def detect_columns(self) -> Dict[str, str]:
        """Detecta as colunas disponiveis na grade (posicao -> nome real)."""
        ...

    @abstractmethod
    def read_grades(self) -> List[Dict]:
        """Le todas as notas visiveis na pagina atual."""
        ...

    @abstractmethod
    def fill_grade(self, aluno: str, nota: str, coluna: str = "") -> bool:
        """Preenche a nota de um aluno. Retorna True se sucesso."""
        ...

    @abstractmethod
    def save(self) -> bool:
        """Salva as alteracoes feitas na pagina."""
        ...

    @abstractmethod
    def is_logged_in(self) -> bool:
        """Verifica se a sessao esta ativa (logado)."""
        ...

    def get_student_sample(self, limit: int = 10) -> List[str]:
        """Retorna uma amostra de nomes de alunos na pagina."""
        return []

    def handle_pagination(self) -> bool:
        """Avanca para a proxima pagina de alunos se existir."""
        return False

    def supports_lesson_plan(self) -> bool:
        """Se o portal suporta planos de aula."""
        return False

    def navigate_to_lesson_plan(self, context: PortalContext) -> bool:
        """Navega ate a secao de planos de aula do portal."""
        return False

    def create_lesson_plan(self, plan: LessonPlan) -> bool:
        """Cria um planejamento com periodo e numero de aulas."""
        return False

    def upload_lesson_plan_pdf(self, titulo: str, pdf_path: str) -> bool:
        """Faz upload de um PDF como anexo do plano de aula."""
        return False
