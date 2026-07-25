import { useEffect, useMemo, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || ''

async function api(path, options = {}, token) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  const text = await response.text()
  const data = text ? JSON.parse(text) : null
  if (!response.ok) {
    throw new Error(data?.detail || data?.message || `请求失败: ${response.status}`)
  }
  return data
}

const emptyCredential = {
  provider_alias: 'openai',
  provider_type: 'openai',
  model_name: 'gpt-5.4-mini',
  reasoning_effort: 'medium',
  base_url: '',
  api_key: ''
}

const emptyWork = {
  title: '',
  prompt: '',
  style: 'default',
  target_chapters: 20,
  budget_usd: '',
  advance_mode: 'auto'
}

function Section({ title, extra, children }) {
  return (
    <section className="card">
      <div className="section-head">
        <h2>{title}</h2>
        {extra}
      </div>
      {children}
    </section>
  )
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [token, setToken] = useState(localStorage.getItem('xiaobai-token') || '')
  const [user, setUser] = useState(() => {
    const raw = localStorage.getItem('xiaobai-user')
    return raw ? JSON.parse(raw) : null
  })
  const [loginForm, setLoginForm] = useState({ username: 'admin', password: 'ChangeMe123!' })
  const [claimForm, setClaimForm] = useState({ code: '', username: '', display_name: '', password: '' })
  const [overview, setOverview] = useState(null)
  const [invites, setInvites] = useState([])
  const [credential, setCredential] = useState(emptyCredential)
  const [savedCredential, setSavedCredential] = useState(null)
  const [works, setWorks] = useState([])
  const [workForm, setWorkForm] = useState(emptyWork)
  const [selectedWorkId, setSelectedWorkId] = useState('')
  const [selectedWork, setSelectedWork] = useState(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  const isAdmin = user?.role === 'admin'

  useEffect(() => {
    api('/api/health').then(setHealth).catch(() => setHealth({ ok: false }))
  }, [])

  useEffect(() => {
    if (!token) return
    refreshAll().catch((error) => setMessage(error.message))
  }, [token])

  useEffect(() => {
    if (!selectedWorkId || !token) return
    loadWork(selectedWorkId).catch((error) => setMessage(error.message))
  }, [selectedWorkId, token])

  async function refreshAll() {
    const [me, system, cred, workList] = await Promise.all([
      api('/api/me', {}, token),
      api('/api/system/overview', {}, token),
      api('/api/credentials/me', {}, token),
      api('/api/works', {}, token)
    ])
    setUser(me.user)
    localStorage.setItem('xiaobai-user', JSON.stringify(me.user))
    setOverview(system)
    setSavedCredential(cred.item)
    setWorks(workList.items)
    if (isAdmin || me.user.role === 'admin') {
      const inviteData = await api('/api/invites', {}, token)
      setInvites(inviteData.items)
    }
    if (workList.items.length && !selectedWorkId) {
      setSelectedWorkId(workList.items[0].id)
    }
  }

  async function loadWork(workId) {
    const detail = await api(`/api/works/${workId}`, {}, token)
    setSelectedWork(detail)
  }

  async function handleLogin(event) {
    event.preventDefault()
    setBusy(true)
    try {
      const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify(loginForm) })
      setToken(data.token)
      localStorage.setItem('xiaobai-token', data.token)
      localStorage.setItem('xiaobai-user', JSON.stringify(data.user))
      setUser(data.user)
      setMessage(`欢迎回来，${data.user.display_name}`)
    } catch (error) {
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleClaim(event) {
    event.preventDefault()
    setBusy(true)
    try {
      const data = await api('/api/auth/claim', { method: 'POST', body: JSON.stringify(claimForm) })
      setMessage(data.message)
      setClaimForm({ code: '', username: '', display_name: '', password: '' })
    } catch (error) {
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  function logout() {
    localStorage.removeItem('xiaobai-token')
    localStorage.removeItem('xiaobai-user')
    setToken('')
    setUser(null)
    setOverview(null)
    setInvites([])
    setSelectedWork(null)
    setSelectedWorkId('')
  }

  async function createInvite() {
    setBusy(true)
    try {
      await api('/api/invites', {
        method: 'POST',
        body: JSON.stringify({ note: 'MVP 邀请', expires_in_hours: 72, max_uses: 1 })
      }, token)
      const inviteData = await api('/api/invites', {}, token)
      setInvites(inviteData.items)
      setMessage('邀请码已创建')
    } catch (error) {
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  async function revokeInvite(inviteId) {
    setBusy(true)
    try {
      await api(`/api/invites/${inviteId}/revoke`, { method: 'POST' }, token)
      const inviteData = await api('/api/invites', {}, token)
      setInvites(inviteData.items)
      setMessage('邀请码已作废')
    } catch (error) {
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  async function saveCredential() {
    setBusy(true)
    try {
      const data = await api('/api/credentials/me', { method: 'PUT', body: JSON.stringify(credential) }, token)
      setMessage(data.message)
      const cred = await api('/api/credentials/me', {}, token)
      setSavedCredential(cred.item)
      setCredential((prev) => ({ ...prev, api_key: '' }))
    } catch (error) {
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  async function testCredential() {
    setBusy(true)
    try {
      const data = await api('/api/credentials/test', { method: 'POST', body: JSON.stringify(credential) }, token)
      setMessage(data.message + (data.base_url_status ? `（HTTP ${data.base_url_status}）` : ''))
    } catch (error) {
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  async function createWork(event) {
    event.preventDefault()
    setBusy(true)
    try {
      const payload = { ...workForm, budget_usd: workForm.budget_usd ? Number(workForm.budget_usd) : null, target_chapters: Number(workForm.target_chapters) }
      const data = await api('/api/works', { method: 'POST', body: JSON.stringify(payload) }, token)
      setMessage(data.message)
      setWorkForm(emptyWork)
      const workList = await api('/api/works', {}, token)
      setWorks(workList.items)
      if (workList.items.length) setSelectedWorkId(workList.items[0].id)
    } catch (error) {
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  async function runAction(action) {
    if (!selectedWorkId) return
    setBusy(true)
    try {
      const data = await api(`/api/works/${selectedWorkId}/runs/${action}`, { method: 'POST' }, token)
      setMessage(data.message)
      await refreshAll()
      await loadWork(selectedWorkId)
    } catch (error) {
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  const stats = useMemo(() => {
    if (!overview) return []
    return [
      ['引擎模式', overview.engine_mode],
      ['我的作品', overview.work_count],
      ['我的活跃运行', `${overview.active_runs_for_user}/${overview.limits.per_operator}`],
      ['全站活跃运行', `${overview.active_runs_global}/${overview.limits.global}`]
    ]
  }, [overview])

  if (!token) {
    return (
      <main className="layout auth-layout">
        <header className="hero card">
          <h1>小白一号</h1>
          <p>邀请制多用户 AI 小说创作控制面。与现网 CLI 栈隔离，默认后台续写。</p>
          <p className="muted">当前引擎模式：{health?.engine_mode || '加载中'}；健康检查：{health?.ok ? '正常' : '未知'}</p>
        </header>
        <div className="grid two-cols">
          <form className="card form" onSubmit={handleLogin}>
            <h2>登录</h2>
            <label>用户名<input value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} /></label>
            <label>密码<input type="password" value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} /></label>
            <button disabled={busy}>登录</button>
          </form>
          <form className="card form" onSubmit={handleClaim}>
            <h2>领取账号</h2>
            <label>邀请码<input value={claimForm.code} onChange={(e) => setClaimForm({ ...claimForm, code: e.target.value })} /></label>
            <label>用户名<input value={claimForm.username} onChange={(e) => setClaimForm({ ...claimForm, username: e.target.value })} /></label>
            <label>显示名<input value={claimForm.display_name} onChange={(e) => setClaimForm({ ...claimForm, display_name: e.target.value })} /></label>
            <label>密码<input type="password" value={claimForm.password} onChange={(e) => setClaimForm({ ...claimForm, password: e.target.value })} /></label>
            <button disabled={busy}>领取账号</button>
          </form>
        </div>
        {message && <p className="message">{message}</p>}
      </main>
    )
  }

  return (
    <main className="layout">
      <header className="hero card">
        <div>
          <h1>小白一号控制面</h1>
          <p>{user?.display_name}（{user?.role === 'admin' ? '管理员' : '操作者'}）已登录</p>
          <p className="muted">剃刀定律：尽量少的部件；墨菲定律：每一步都留回退与验证。</p>
        </div>
        <div className="actions">
          <button className="secondary" onClick={() => refreshAll().then(() => selectedWorkId && loadWork(selectedWorkId))}>刷新</button>
          <button className="secondary" onClick={logout}>退出</button>
        </div>
      </header>

      {message && <p className="message">{message}</p>}

      <section className="stats-grid">
        {stats.map(([label, value]) => (
          <div className="stat card" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </section>

      <div className="grid main-grid">
        <div className="column">
          {isAdmin && (
            <Section title="邀请码管理" extra={<button onClick={createInvite} disabled={busy}>新建邀请码</button>}>
              <div className="invite-list">
                {invites.map((invite) => (
                  <div className="list-item" key={invite.id}>
                    <div>
                      <strong>{invite.code}</strong>
                      <div className="muted">{invite.note || '无备注'} · {invite.used_count}/{invite.max_uses} · {invite.revoked_at ? '已作废' : '有效'}</div>
                    </div>
                    {!invite.revoked_at && <button className="secondary" onClick={() => revokeInvite(invite.id)}>作废</button>}
                  </div>
                ))}
                {!invites.length && <p className="muted">还没有邀请码。</p>}
              </div>
            </Section>
          )}

          <Section title="模型凭证设置" extra={<span className="pill">仅自己可见</span>}>
            <div className="form two-cols compact">
              <label>Provider 别名<input value={credential.provider_alias} onChange={(e) => setCredential({ ...credential, provider_alias: e.target.value })} /></label>
              <label>Provider 类型<input value={credential.provider_type || ''} onChange={(e) => setCredential({ ...credential, provider_type: e.target.value })} placeholder="openai / openrouter / anthropic" /></label>
              <label>模型名<input value={credential.model_name} onChange={(e) => setCredential({ ...credential, model_name: e.target.value })} /></label>
              <label>推理强度<input value={credential.reasoning_effort} onChange={(e) => setCredential({ ...credential, reasoning_effort: e.target.value })} /></label>
              <label className="full">Base URL<input value={credential.base_url || ''} onChange={(e) => setCredential({ ...credential, base_url: e.target.value })} placeholder="可留空" /></label>
              <label className="full">API Key<input type="password" value={credential.api_key} onChange={(e) => setCredential({ ...credential, api_key: e.target.value })} placeholder={savedCredential?.masked_api_key || '输入新的 Key'} /></label>
            </div>
            <div className="actions">
              <button onClick={testCredential} disabled={busy || !credential.api_key}>连接预检</button>
              <button onClick={saveCredential} disabled={busy || !credential.api_key}>保存凭证</button>
            </div>
            {savedCredential && <p className="muted">最近保存：{savedCredential.model_name} · {savedCredential.masked_api_key}</p>}
          </Section>

          <Section title="新建作品（快速开始）">
            <form className="form" onSubmit={createWork}>
              <label>作品名<input value={workForm.title} onChange={(e) => setWorkForm({ ...workForm, title: e.target.value })} /></label>
              <label>一句话创作指令<textarea rows="4" value={workForm.prompt} onChange={(e) => setWorkForm({ ...workForm, prompt: e.target.value })} /></label>
              <div className="form two-cols compact">
                <label>风格<input value={workForm.style} onChange={(e) => setWorkForm({ ...workForm, style: e.target.value })} /></label>
                <label>推进方式<select value={workForm.advance_mode} onChange={(e) => setWorkForm({ ...workForm, advance_mode: e.target.value })}><option value="auto">自动模式</option><option value="review">逐章验收</option></select></label>
                <label>目标章节<input type="number" value={workForm.target_chapters} onChange={(e) => setWorkForm({ ...workForm, target_chapters: e.target.value })} /></label>
                <label>预算(USD)<input type="number" value={workForm.budget_usd} onChange={(e) => setWorkForm({ ...workForm, budget_usd: e.target.value })} placeholder="可留空" /></label>
              </div>
              <button disabled={busy}>创建作品</button>
            </form>
          </Section>
        </div>

        <div className="column">
          <Section title="作品列表">
            <div className="work-list">
              {works.map((work) => (
                <button key={work.id} className={`work-item ${selectedWorkId === work.id ? 'active' : ''}`} onClick={() => setSelectedWorkId(work.id)}>
                  <strong>{work.title}</strong>
                  <span>{work.status} · {work.completed_chapters}/{work.target_chapters || '?'}</span>
                </button>
              ))}
              {!works.length && <p className="muted">还没有作品，先创建一本。</p>}
            </div>
          </Section>

          <Section title="创作工作台" extra={selectedWork && <span className="pill">{selectedWork.work.status}</span>}>
            {!selectedWork && <p className="muted">请选择一部作品。</p>}
            {selectedWork && (
              <>
                <div className="detail-grid">
                  <div><span>作品</span><strong>{selectedWork.work.title}</strong></div>
                  <div><span>阶段</span><strong>{selectedWork.work.current_phase}</strong></div>
                  <div><span>流程</span><strong>{selectedWork.work.current_flow}</strong></div>
                  <div><span>已完成章节</span><strong>{selectedWork.work.completed_chapters}</strong></div>
                </div>
                <p className="muted">快速开始：{selectedWork.work.prompt}</p>
                {selectedWork.work.last_error && <p className="error">错误：{selectedWork.work.last_error}</p>}
                <div className="actions">
                  <button onClick={() => runAction('start')} disabled={busy}>开始</button>
                  <button className="secondary" onClick={() => runAction('pause')} disabled={busy}>暂停</button>
                  <button className="secondary" onClick={() => runAction('continue')} disabled={busy}>继续创作</button>
                </div>
                <h3>运行记录</h3>
                <div className="timeline">
                  {selectedWork.runs.map((run) => (
                    <div className="list-item" key={run.id}>
                      <div>
                        <strong>{run.id}</strong>
                        <div className="muted">{run.mode} · {run.status} · {run.started_at || '未开始'}</div>
                      </div>
                      {run.container_name && <span className="pill">{run.container_name}</span>}
                    </div>
                  ))}
                  {!selectedWork.runs.length && <p className="muted">还没有运行记录。</p>}
                </div>
              </>
            )}
          </Section>

          <Section title="产物浏览（只读）">
            {!selectedWork?.artifacts?.length && <p className="muted">暂无产物。mock 模式下启动后会自动生成大纲、进度与章节文件。</p>}
            <div className="artifact-list">
              {selectedWork?.artifacts?.map((artifact) => (
                <details className="artifact" key={artifact.path}>
                  <summary>{artifact.path} <span className="muted">({artifact.size} bytes)</span></summary>
                  <pre>{artifact.preview}</pre>
                </details>
              ))}
            </div>
          </Section>
        </div>
      </div>
    </main>
  )
}
