import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import os
import sys
import time
import argparse
from typing import List, Tuple, Optional, Dict, Any

from dotenv import load_dotenv
from openai import OpenAI
from typing_extensions import override

# =========================
# Config & bootstrap
# =========================
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "0.8"))
POLL_TIMEOUT_S = int(os.getenv("POLL_TIMEOUT_S", "120"))  # 2 min
BACKOFF_FACTOR = float(os.getenv("BACKOFF_FACTOR", "1.15"))  # leve backoff


# =========================
# Cargar IDs de asistentes
# =========================
def load_agent_ids(path: str = "agent_ids.env") -> Dict[str, str]:
    ids = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            ids[k] = v
    return ids


AGENTS = load_agent_ids()

AGENT_MAP = {
    "comercial": AGENTS["AGENTE_COMERCIAL"],
    "soporte": AGENTS["AGENTE_SOPORTE"],
    "documental": AGENTS["AGENTE_DOCUMENTAL"],
}


# =========================
# Utilidades de citas
# =========================
def extract_answer_and_citations_from_message(message) -> Tuple[str, List[str]]:
    """
    Extrae texto y referencias de archivos (si existen) del último mensaje del asistente.
    Usa anotaciones del mensaje.
    """
    text_out: List[str] = []
    citations: List[str] = []

    for part in message.content:
        if part.type != "text":
            continue
        text_obj = part.text
        value = text_obj.value or ""
        annotations = getattr(text_obj, "annotations", []) or []

        # Reemplazar el fragmento anotado por [n] y acumular filenames citados
        for idx, ann in enumerate(annotations):
            try:
                # Reemplaza el texto anotado por [n]
                if hasattr(ann, "text") and ann.text:
                    value = value.replace(ann.text, f"[{idx}]")
                # Si hay file_citation, obtener filename
                file_citation = getattr(ann, "file_citation", None)
                if file_citation and getattr(file_citation, "file_id", None):
                    meta = client.files.retrieve(file_citation.file_id)
                    citations.append(
                        f"[{idx}] {getattr(meta, 'filename', file_citation.file_id)}"
                    )
            except Exception:
                # Silencioso si alguna anotación falla
                pass

        if value:
            text_out.append(value)

    return ("\n".join(text_out).strip(), citations)


def try_fetch_file_search_chunks(thread_id: str, run_id: str) -> List[str]:
    """
    Intenta obtener detalles de File Search desde los run steps.
    Si el SDK expone `include`, listamos los steps y tratamos de recuperar
    contenidos citados. Si no, devolvemos lista vacía sin fallar.
    """
    chunks: List[str] = []
    try:
        steps = client.beta.threads.runs.steps.list(thread_id=thread_id, run_id=run_id)
        for step in steps.data:
            sd = getattr(step, "step_details", None)
            if not sd:
                continue
            tool_calls = getattr(sd, "tool_calls", []) or []
            for tc in tool_calls:
                if getattr(tc, "type", "") != "file_search":
                    continue
                results = getattr(tc, "file_search", None)
                if not results:
                    continue
                # Algunos SDKs no exponen directamente los 'content' aquí.
                items = getattr(results, "results", []) or []
                for r in items:
                    content_list = getattr(r, "content", []) or []
                    for c in content_list:
                        # c puede tener .type == "text" con .text.value
                        if getattr(c, "type", None) == "text":
                            txt = getattr(getattr(c, "text", None), "value", None)
                            if txt:
                                chunks.append(txt)
    except Exception:
        # Silencioso: si no está disponible en tu versión, no rompemos.
        pass
    return chunks


# =========================
# Polling robusto del run
# =========================
def poll_run(thread_id: str, run_id: str, timeout_s: int = POLL_TIMEOUT_S) -> Any:
    """
    Hace polling hasta que el run termina o vence el timeout.
    Devuelve el objeto run final.
    """
    start = time.time()
    interval = POLL_INTERVAL
    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        if run.status not in ("queued", "in_progress", "requires_action"):
            return run
        if time.time() - start > timeout_s:
            # devolvemos el estado actual (probablemente en progreso)
            return run
        time.sleep(interval)
        interval = min(interval * BACKOFF_FACTOR, 2.0)  # no más de 2s


# =========================
# Opcional: Streaming
# =========================
try:
    from openai import AssistantEventHandler
    HAVE_STREAMING = True
except Exception:
    HAVE_STREAMING = False


if HAVE_STREAMING:
    class StreamHandler(AssistantEventHandler):
        @override
        def on_text_created(self, text) -> None:
            print("\nassistant >", end="", flush=True)

        @override
        def on_tool_call_created(self, tool_call):
            print(f"\nassistant > {tool_call.type}\n", flush=True)

        @override
        def on_message_done(self, message) -> None:
            ans, cites = extract_answer_and_citations_from_message(message)
            print(ans)
            if cites:
                print("\n=== Citas ===")
                for c in cites:
                    print("-", c)


# =========================
# Runner principal
# =========================
def ask(
    assistant_id: str,
    question: str,
    *,
    stream: bool = False,
    extra_instructions: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """
    Crea un thread, envía la pregunta y ejecuta un run (con o sin streaming).
    Devuelve (texto, citas). En streaming imprime en vivo y retorna textos vacíos.
    """
    # 1) Crear thread con el mensaje del usuario
    messages = [{"role": "user", "content": question}]
    if extra_instructions:
        # Puedes enriquecer el contexto de la conversación agregando system-like prompt como primer mensaje
        messages.insert(0, {"role": "assistant", "content": extra_instructions})

    thread = client.beta.threads.create(messages=messages)

    # STREAMING: imprime en vivo y retorna vacío (impresión ya hecha)
    if stream and HAVE_STREAMING:
        # Nota: puedes pasar instrucciones específicas del run aquí si quieres:
        with client.beta.threads.runs.stream(
            thread_id=thread.id,
            assistant_id=assistant_id,
            event_handler=StreamHandler(),
        ) as s:
            s.until_done()
        return ("", [])

    # 2) Crear run
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant_id,
        # instructions=extra_instructions or None,  # opcional
    )

    # 3) Polling robusto
    run = poll_run(thread.id, run.id, timeout_s=POLL_TIMEOUT_S)

    # 4) Resolver estados
    if run.status == "requires_action":
        # Aquí podrías manejar tool-calls (function calling) si agregas tools custom.
        # Por ahora, terminamos elegante:
        return ("[INFO] El asistente solicitó una acción (tool call). Aún no implementado en este runner.", [])

    if run.status != "completed":
        return (f"[ERROR] Run terminó con estado: {run.status}", [])

    # 5) Obtener último mensaje
    msgs = client.beta.threads.messages.list(thread_id=thread.id, order="desc", limit=10)
    for m in msgs.data:
        if m.role == "assistant":
            answer, cites = extract_answer_and_citations_from_message(m)

            # Extra: intentar traer trozos (chunks) de File Search usados
            fs_chunks = try_fetch_file_search_chunks(thread.id, run.id)
            if fs_chunks:
                # No saturar salida; solo decimos cuántos chunks
                answer += f"\n\n[debug] Chunks usados: {len(fs_chunks)}"
            return (answer or "[Sin texto]", cites)

    return ("[Sin respuesta del asistente]", [])


# =========================
# CLI
# =========================
def parse_args():
    p = argparse.ArgumentParser(description="Pregunta a un assistant (Assistants β)")
    p.add_argument("agent", choices=["comercial", "soporte", "documental"], help="Agente objetivo")
    p.add_argument("question", nargs="+", help="Pregunta al agente")
    p.add_argument("--stream", action="store_true", help="Usar streaming (si está disponible en el SDK)")
    p.add_argument("--extra", type=str, default=None, help="Instrucciones adicionales para este run")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    target = args.agent.lower()
    question = " ".join(args.question)

    if target not in AGENT_MAP:
        print("Agente inválido. Usa: comercial | soporte | documental")
        sys.exit(1)

    assistant_id = AGENT_MAP[target]
    text, cites = ask(assistant_id, question, stream=args.stream, extra_instructions=args.extra)

    # En streaming ya se imprimió
    if args.stream and HAVE_STREAMING:
        sys.exit(0)

    print("\n=== Respuesta ===")
    print(text)
    if cites:
        print("\n=== Citas ===")
        for c in cites:
            print("-", c)
