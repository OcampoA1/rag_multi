import React from "react"
import { api } from "./api"
import { Send, Upload, ChevronDown } from "lucide-react"

const AGENTS = ["comercial", "soporte", "documental"] as const
type Agent = typeof AGENTS[number]
type Msg = { role: "user" | "assistant"; text: string }

export default function App() {
  const [agent, setAgent] = React.useState<Agent>("comercial")
  const [tab, setTab] = React.useState<"chat" | "datos">("chat")

  return (
    <div className="min-h-screen grid grid-rows-[auto,1fr]">
      {/* Topbar */}
      <header className="bg-white border-b">
        <div className="max-w-6xl mx-auto flex items-center justify-between p-4">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-indigo-600 text-white grid place-items-center font-bold">MA</div>
            <div>
              <div className="font-semibold">Multi-Agente RAG</div>
              <div className="text-xs text-slate-500">Chat + Carga de documentos</div>
            </div>
          </div>

          {/* Perfil (invitado) */}
          <div className="relative group">
            <button className="flex items-center gap-2 bg-slate-100 hover:bg-slate-200 rounded-lg px-3 py-1.5">
              <div className="h-7 w-7 rounded-full bg-indigo-500 text-white grid place-items-center text-sm">I</div>
              <div className="text-left">
                <div className="text-sm font-medium leading-4">Invitado</div>
                <div className="text-xs text-slate-500">invitado@example.com</div>
              </div>
              <ChevronDown className="h-4 w-4" />
            </button>
            <div className="absolute right-0 mt-2 w-56 bg-white border rounded-xl shadow-xl p-3 hidden group-hover:block">
              <div className="text-sm"><span className="font-semibold">Rol:</span> público</div>
              <div className="text-xs text-slate-500 mt-1">Modo público habilitado</div>
            </div>
          </div>
        </div>
      </header>

      {/* Body */}
      <main className="max-w-6xl mx-auto w-full grid grid-cols-1 lg:grid-cols-[220px,1fr] gap-4 p-4">
        {/* Sidebar */}
        <aside className="bg-white rounded-2xl border p-4 h-fit">
          <div className="text-sm text-slate-500 mb-2">Agente</div>
          <select
            value={agent}
            onChange={(e) => setAgent(e.target.value as Agent)}
            className="w-full border rounded-lg p-2"
          >
            {AGENTS.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>

          <div className="mt-6 text-sm text-slate-500 mb-2">Vistas</div>
          <div className="grid grid-cols-2 gap-2">
            <button onClick={() => setTab("chat")} className={`rounded-lg py-2 ${tab === "chat" ? "bg-indigo-600 text-white" : "bg-slate-100"}`}>Chat</button>
            <button onClick={() => setTab("datos")} className={`rounded-lg py-2 ${tab === "datos" ? "bg-indigo-600 text-white" : "bg-slate-100"}`}>Datos</button>
          </div>
        </aside>

        {/* Panel principal */}
        <section className="bg-white rounded-2xl border p-4 min-h-[70vh]">
          {tab === "chat" ? <ChatPanel agent={agent} /> : <DataPanel agent={agent} />}
        </section>
      </main>
    </div>
  )
}

function ChatPanel({ agent }: { agent: Agent }) {
  const [q, setQ] = React.useState("Hola, ¿qué puedes hacer por mí?")
  const [loading, setLoading] = React.useState(false)
  const [msgs, setMsgs] = React.useState<Msg[]>([])

  async function send() {
    if (!q.trim()) return
    const userMsg: Msg = { role: "user", text: q }
    setMsgs((m) => [...m, userMsg]); setQ(""); setLoading(true)
    try {
      const { data } = await api.post("/chat/ask", { agent, question: userMsg.text })
      const ans: Msg = { role: "assistant", text: data.answer }
      setMsgs((m) => [...m, ans])
    } catch (e: any) {
      const ans: Msg = { role: "assistant", text: `Error: ${e?.response?.data?.detail || "no se pudo obtener respuesta"}` }
      setMsgs((m) => [...m, ans])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full grid grid-rows-[1fr,auto] gap-3">
      <div className="space-y-3 overflow-y-auto pr-2">
        {msgs.length === 0 && (
          <div className="text-center text-slate-500 mt-10">
            Empieza a chatear con el agente <span className="font-semibold">{agent}</span>.
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`max-w-[80%] ${m.role === "user" ? "ml-auto" : ""}`}>
            <div className={`px-4 py-2 rounded-2xl border ${m.role === "user" ? "bg-indigo-50 border-indigo-200" : "bg-slate-50 border-slate-200"}`}>
              {m.text}
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={`Pregunta al agente ${agent}...`}
          className="flex-1 border rounded-xl p-3"
        />
        <button
          onClick={send}
          disabled={loading}
          className="rounded-xl bg-indigo-600 text-white px-4 py-2 flex items-center gap-2 hover:opacity-95 disabled:opacity-60"
        >
          <Send className="h-4 w-4" /> Enviar
        </button>
      </div>
    </div>
  )
}

function DataPanel({ agent }: { agent: Agent }) {
  const [file, setFile] = React.useState<File | null>(null)
  const [status, setStatus] = React.useState<string>("")

  async function upload() {
    if (!file) return
    const fd = new FormData()
    fd.append("agent", agent)
    fd.append("file", file)
    setStatus("Subiendo...")
    try {
      const { data } = await api.post("/vs/upload", fd, { headers: { "Content-Type": "multipart/form-data" } })
      setStatus(`OK: ${data.filename} → ${data.vector_store}`)
    } catch (e: any) {
      setStatus(`Error: ${e?.response?.data?.detail || "falló el upload"}`)
    }
  }

  return (
    <div className="max-w-lg">
      <div className="text-sm text-slate-500">
        Sube documentos a la base vectorial del agente <span className="font-semibold">{agent}</span>.
      </div>
      <div className="mt-3 flex items-center gap-2">
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} className="block w-full text-sm" />
        <button onClick={upload} className="rounded-xl bg-emerald-600 text-white px-4 py-2 flex items-center gap-2 hover:opacity-95">
          <Upload className="h-4 w-4" /> Subir
        </button>
      </div>
      {status && <div className="mt-3 text-sm">{status}</div>}
      <div className="mt-6 text-xs text-slate-500">Formatos aceptados: .pdf, .docx, .txt, .md, .csv</div>
    </div>
  )
}
