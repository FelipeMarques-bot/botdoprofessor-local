"""Servico de download protegido do binario (Cloudflare R2 / S3-compatible).

O binario fica em um bucket PRIVADO. O download so e liberado apos
validar a chave de licenca (ativa e nao expirada), gerando uma URL
assinada temporaria via API S3-compatible (boto3).

Variaveis de ambiente (ver .env.example):
  STORAGE_ENDPOINT    - endpoint S3 do bucket (R2 usa https://<account>.r2.cloudflarestorage.com)
  STORAGE_ACCESS_KEY  - Access Key ID
  STORAGE_SECRET_KEY  - Secret Access Key
  STORAGE_BUCKET      - nome do bucket privado
  STORAGE_OBJECT      - chave (nome) do objeto dentro do bucket (padrao: BotDoProfessor.exe)
  STORAGE_REGION      - regiao (R2: auto)
  DOWNLOAD_URL_TTL    - segundos de validade da URL assinada (padrao: 600)
"""
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


def resolve_download(license_key: str):
    """Valida a licenca e, se valida, gera uma URL assinada temporaria.

    Retorna (download_url, error). Se `error` nao for None, nao libera o download.
    """
    if not license_key:
        return None, "Chave de licenca ausente. Acesse o link enviado por email."

    if not _storage_configured():
        return None, "Storage nao configurado no servidor. Contate o suporte."

    result = LicenseService.validate(license_key)
    if not result.get("valid"):
        return None, result.get("error", "Licenca invalida ou expirada.")

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

    return url, None
