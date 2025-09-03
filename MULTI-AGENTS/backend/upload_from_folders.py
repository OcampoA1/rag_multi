# upload_from_folders.py
import os, sys
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# --- Config ---
FOLDER_TO_VS_KEY = {
    "doc_comercial": "VS_COMERCIAL",
    "doc_soporte": "VS_SOPORTE",
    "doc_documentos": "VS_DOCUMENTAL",
}
ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".md", ".csv"}  # puedes ampliar

def load_vs_ids(env_path="vector_store_ids.env"):
    ids = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): 
                continue
            k, v = line.strip().split("=", 1)
            ids[k] = v
    return ids

def iter_files(root: Path):
    for folder_name in FOLDER_TO_VS_KEY.keys():
        folder = root / folder_name
        if not folder.exists():
            print(f"[WARN] Carpeta no encontrada: {folder}")
            continue
        for p in folder.rglob("*"):
            if p.is_file() and p.suffix.lower() in ALLOWED_EXTS:
                yield folder_name, p

def main():
    load_dotenv()
    client = OpenAI()
    vs_ids = load_vs_ids()

    root = Path(".").resolve()
    total, ok, skipped, failed = 0, 0, 0, 0

    print("== Iniciando carga desde carpetas ==")
    for folder_name, path in iter_files(root):
        total += 1
        vs_key = FOLDER_TO_VS_KEY[folder_name]
        vs_id = vs_ids.get(vs_key)
        if not vs_id:
            print(f"[ERROR] No encuentro ID para {vs_key} en vector_store_ids.env. Omitiendo {path.name}")
            failed += 1
            continue

        # Evita volver a subir el mismo archivo exacto (opcional: por nombre)
        # Puedes cambiar esta lógica por hashes si quieres algo más estricto.
        try:
            print(f"[SUBIENDO] {folder_name} -> {path.name}")
            up = client.files.create(file=open(path, "rb"), purpose="assistants")
            client.vector_stores.files.create(vector_store_id=vs_id, file_id=up.id)
            ok += 1
        except Exception as e:
            failed += 1
            print(f"[ERROR] {path.name}: {e}")

    print("\n== Resumen ==")
    print(f"Total encontrados: {total}")
    print(f"Subidos OK:       {ok}")
    print(f"Omitidos:         {skipped}")
    print(f"Con error:        {failed}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
