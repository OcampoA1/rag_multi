import os
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from openai import OpenAI
from pydantic import BaseModel

# ================== Cargar .env junto a este archivo ==================
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

# Importa utilidades de agentes (tu archivo ask_agent.py debe estar aquí)
import ask_agent  # requiere ask_agent.py

# ================== Seguridad / JWT ==================
SECRET_KEY = os.getenv("JWT_SECRET", "change_me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 8 * 60

# 👇 CLAVE DEL ARREGLO: no auto-error si falta token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# ================== Modo Público ==================
PUBLIC_MODE = os.getenv("PUBLIC_MODE", "false").lower() == "true"

# ================== FastAPI ==================
app = FastAPI(title="Multi-Agente RAG API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================== Modelos ==================
class Token(BaseModel):
    access_token: str
    token_type: str

class User(BaseModel):
    username: str
    name: str
    email: str
    role: str = "admin"

class AskPayload(BaseModel):
    agent: str
    question: str

# ================== Helpers Auth ==================
def authenticate(username: str, password: str) -> Optional[User]:
    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")
    if username == admin_user and password == admin_pass:
        return User(
            username=username,
            name=os.getenv("ADMIN_NAME", "Alejandro"),
            email=os.getenv("ADMIN_EMAIL", "admin@example.com"),
        )
    return None

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_user_from_token_str(token: str) -> User:
    credentials_exception = HTTPException(status_code=401, detail="No autorizado")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        name: str = payload.get("name")
        email: str = payload.get("email")
        role: str = payload.get("role", "admin")
        if username is None:
            raise credentials_exception
        return User(username=username, name=name, email=email, role=role)
    except JWTError:
        raise credentials_exception

def require_user(token: Optional[str] = Depends(oauth2_scheme)) -> User:
    """
    Si PUBLIC_MODE=True, no exige token y devuelve un usuario ficticio.
    Si PUBLIC_MODE=False, exige token y valida JWT.
    """
    if PUBLIC_MODE:
        return User(username="public", name="Invitado", email="invitado@example.com", role="public")
    if not token:
        # Modo privado y sin token -> 401
        raise HTTPException(status_code=401, detail="No autorizado")
    return get_user_from_token_str(token)

# ================== Endpoints Auth ==================
@app.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Usuario o contraseña inválidos")
    token = create_access_token({
        "sub": user.username,
        "name": user.name,
        "email": user.email,
        "role": user.role,
    })
    return {"access_token": token, "token_type": "bearer"}

@app.get("/auth/me", response_model=User)
def me(current_user: User = Depends(require_user)):
    return current_user

# ================== Agentes & Chat ==================
@app.get("/agents")
def list_agents(current_user: User = Depends(require_user)):
    return {"agents": list(ask_agent.AGENT_MAP.keys())}

@app.post("/chat/ask")
def chat_ask(payload: AskPayload, current_user: User = Depends(require_user)):
    agent = payload.agent.lower()
    if agent not in ask_agent.AGENT_MAP:
        raise HTTPException(status_code=400, detail="Agente inválido")
    assistant_id = ask_agent.AGENT_MAP[agent]
    text, cites = ask_agent.ask(assistant_id, payload.question, stream=False)
    return {"answer": text, "citations": cites}

# ================== Vector Stores (upload) ==================
VS_KEYS = {"comercial": "VS_COMERCIAL", "soporte": "VS_SOPORTE", "documental": "VS_DOCUMENTAL"}
ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".md", ".csv"}

def load_vs_ids(path="vector_store_ids.env"):
    ids = {}
    if not os.path.exists(path):
        raise RuntimeError("No se encontró vector_store_ids.env")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            ids[k] = v
    return ids

@app.post("/vs/upload")
def upload_to_vector_store(
    agent: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(require_user),
):
    agent = agent.lower()
    if agent not in VS_KEYS:
        raise HTTPException(status_code=400, detail="Agente inválido")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Extensión no permitida: {ext}")

    vs_ids = load_vs_ids()
    vs_key = VS_KEYS[agent]
    vs_id = vs_ids.get(vs_key)
    if not vs_id:
        raise HTTPException(status_code=500, detail=f"No hay ID para {vs_key} en vector_store_ids.env")

    client = OpenAI()
    
    try:
        # Reinicia el puntero del archivo
        file.file.seek(0)

        # Pasar como tupla (nombre, fileobj, content_type) → compatible con SDK 1.x
        uploaded = client.files.create(
            file=(file.filename, file.file, file.content_type or "application/octet-stream"),
            purpose="assistants",
        )

        client.vector_stores.files.create(
            vector_store_id=vs_id,
            file_id=uploaded.id
        )

        return {
            "status": "ok",
            "filename": file.filename,
            "vector_store": vs_key,
            "vector_store_id": vs_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ================== Opcional: raíz y healthcheck ==================
@app.get("/", include_in_schema=False)
def root():
    return {"status": "ok", "public_mode": PUBLIC_MODE, "docs": "/docs"}

@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
