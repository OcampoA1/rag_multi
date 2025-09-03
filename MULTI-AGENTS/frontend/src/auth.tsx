import React, { createContext, useContext, useEffect, useState } from 'react'
import { api, setAuth } from './api'

type User = { username: string; name: string; email: string; role: string }

type AuthCtx = {
  user: User | null
  token: string | null
  login: (u: string, p: string) => Promise<void>
  logout: () => void
}

const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'))
  const [user, setUser] = useState<User | null>(null)

  useEffect(() => { setAuth(token || null); if (token) api.get('/auth/me').then(r => setUser(r.data)).catch(() => logout()) }, [token])

  async function login(username: string, password: string) {
    const { data } = await api.post('/auth/login', new URLSearchParams({ username, password }))
    localStorage.setItem('token', data.access_token)
    setToken(data.access_token)
  }
  function logout() { localStorage.removeItem('token'); setToken(null); setUser(null) }

  return <Ctx.Provider value={{ user, token, login, logout }}>{children}</Ctx.Provider>
}

export function useAuth() { return useContext(Ctx) }