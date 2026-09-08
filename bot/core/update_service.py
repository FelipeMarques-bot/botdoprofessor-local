"""Servico de verificacao de atualizacao do binario (Cloudflare R2 / S3-compatible).

O launcher (ver launcher.py) consulta /api/check-update antes de abrir o painel.
Este servico valida a licenca, le a versao publicada no bucket (version.json) e,
se houver versao mais nova que a instalada localmente, devolve uma URL assinada
temporaria para o download do novo .exe.

Bucket PRIVADO, mesmo fluxo de seguranca do download_service.

Variaveis de ambiente (ver .env.example):
  STORAGE_ENDPOINT        - endpoint S3 do bucket (R2 usa https://<account>.r2.cloudflarestorage.com)
  STORAGE_ACCESS_KEY      - Access Key ID
  STORAGE_SECRET_KEY      - Secret Access Key
  STORAGE_BUCKET          - nome do bucket privado
  STORAGE_OBJECT          - chave (nome) do objeto .exe dentro do bucket (padrao: BotDoProfessor.exe)
  STORAGE_VERSION_OBJECT  - chave do objeto de versao (padrao: version.json)
  STORAGE_REGION          - regiao (R2: auto)
  DOWNLOAD_URL_TTL        - segundos de validade da URL assinada (padrao: 600)
"""
import json
import os

from bot.core.license_service import LicenseService


def _storage_configured() -> bool:
    return all([
        os.environ.get("STORAGE_ENDPOINT"),
        os.environ.get("STORAGE_ACCESS_KEY"),
        os.environ.get("STORAGE_SECRET_KEY"),
        os.environ.get("STORAGE_BUCKET"),
    ])


def _get_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["STORAGE_ENDPOINT"],
        aws_access_key_id=os.environ["STORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["STORAGE_SECRET_KEY"],
        region_name=os.environ.get("STORAGE_REGION", "auto"),
    )


def _version_object() -> str:
    return os.environ.get("STORAGE_VERSION_OBJECT", "version.json")


def parse_version(version: str):
    """Converte '1.4.40' (pode ter sufixo) em tupla de numeros comparavel."""
    if not version:
        return (0,)
    import re
    nums = re.findall(r"\d+", str(version))
    try:
        parts = [int(n) for n in nums]
    except ValueError:
        return (0,)
    return tuple(parts) or (0,)


def _read_remote_version() -> str:
    """Le o version.json publicado no bucket. Retorna '' se nao existir."""
    client = _get_client()
    resp = client.get_object(
        Bucket=os.environ["STORAGE_BUCKET"],
        Key=_version_object(),
    )
    body = resp.get("Body")
    raw = body.read().decode("utf-8", errors="replace") if body else ""
    data = json.loads(raw)
    return str(data.get("version", "") or "").strip()


def check_update(license_key: str, current_version: str):
    """Valida a licenca e compara a versao do bucket com a versao local.

    Retorna (result, error). Se `error` nao for None, nao ha decisao.
    `result` tem o formato:
      {"update": bool, "version": str, "download_url": str|None}
    """
    if not license_key:
        return None, "Chave de licenca ausente. Acesse o link enviado por email."

    if not _storage_configured():
        return None, "Storage nao configurado no servidor. Contate o suporte."

    result = LicenseService.validate(license_key)
    if not result.get("valid"):
        return None, result.get("error", "Licenca invalida ou expirada.")

    try:
        remote_version = _read_remote_version()
    except Exception as e:  # pragma: no cover - depende de rede/credenciais
        return None, f"Erro ao ler a versao publicada: {e}"

    if not remote_version:
        return {"update": False, "version": "", "download_url": None}, None

    local = parse_version(current_version)
    remote = parse_version(remote_version)

    if remote <= local:
        return {"update": False, "version": remote_version, "download_url": None}, None

    try:
        ttl = int(os.environ.get("DOWNLOAD_URL_TTL", "600"))
    except ValueError:
        ttl = 600

    try:
        client = _get_client()
        url = client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": os.environ["STORAGE_BUCKET"],
                "Key": os.environ.get("STORAGE_OBJECT", "BotDoProfessor.exe"),
                "ResponseContentDisposition": "attachment; filename=BotDoProfessor.exe",
            },
            ExpiresIn=ttl,
        )
    except Exception as e:  # pragma: no cover - depende de rede/credenciais
        return None, f"Erro ao preparar o download: {e}"

    return {"update": True, "version": remote_version, "download_url": url}, None