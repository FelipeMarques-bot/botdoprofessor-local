"""Envia o binario atual (dist/BotDoProfessor.exe) para o bucket R2 privado.

Uso:
  python upload_binario.py [caminho_do_exe]

Pre-requisito: variaveis de ambiente STORAGE_* configuradas no .env
(ver .env.example). Depois que o .exe estiver no bucket, o download so
e liberado via /api/download com chave de licenca valida.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=False)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "dist/BotDoProfessor.exe"

    required = ["STORAGE_ENDPOINT", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY", "STORAGE_BUCKET"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print("ERRO: faltam variaveis de storage no .env:", ", ".join(missing))
        sys.exit(1)

    if not os.path.exists(path):
        print(f"ERRO: arquivo nao encontrado: {path}")
        sys.exit(1)

    obj = os.environ.get("STORAGE_OBJECT", "BotDoProfessor.exe")

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["STORAGE_ENDPOINT"],
        aws_access_key_id=os.environ["STORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["STORAGE_SECRET_KEY"],
        region_name=os.environ.get("STORAGE_REGION", "auto"),
    )

    print(f"Enviando {path} -> s3://{os.environ['STORAGE_BUCKET']}/{obj} ...")
    client.upload_file(path, os.environ["STORAGE_BUCKET"], obj, ExtraArgs={"ContentType": "application/x-msdownload"})
    size = os.path.getsize(path)
    print(f"Upload concluido: {size} bytes")


if __name__ == "__main__":
    main()
