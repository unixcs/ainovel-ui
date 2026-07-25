import { useEffect, useMemo, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || ''

function formatApiError(data, status) {
  if (!data) return `请求失败: ${status}`
  if (typeof data === 'string') return data
  if (Array.isArray(data)) {
    return data.map((item) => formatApiError(item, status)).join('；')
  }
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((item) => {
        if (typeof item === 'string') return item
        const loc = Array.isArray(item.loc) ? item.loc.join('.') : ''
        const msg = item.msg || item.message || JSON.stringify(item)
        return loc ? `${loc}: ${msg}` : msg
      })
      .join('；')
  }
  if (typeof data.detail === 'string') return data.detail
  if (typeof data.message === 'string') return data.message
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

async function api(path, options = {}, token) {
  const headers = { ...(options.headers || {}) }
  if (!(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  const contentType = response.headers.get('content-type') || ''
  const text = await response.text()
  const data = contentType.includes('application/json') ? (text ? JSON.parse(text) : null) : text
  if (!response.ok) {
    throw new Error(formatApiError(data, response.status))
  }
  return data
}

async function downloadFile(path, filename, token) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {}
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `下载失败: ${response.status}`)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
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

const emptyPassword = {
  current_password: '',
  new_password: '',
  confirm_password: ''
}

function Section({ title, extra, children }) {
  return (
    <section className="card section-card">
      <div className="section-head">
        <h2>{title}</h2>
        {extra}
      </div>
      {children}
    </section>
  )
}

function StatusPill({ children, tone = 'default' }) {
  return <span className={`pill pill-${tone}`}>{children}</span>
}

function formatInviteStatus(invite) {
  if (invite.revoked_at) return ['已作废', 'danger']
  if (invite.used_count >= invite.max_uses) return ['已用完', 'muted']
  if (invite.expires_at && new Date(invite.expires_at).getTime() < Date.now()) return ['已过期', 'danger']
  return ['可领取', 'success']
}

function chapterFileName(chapter) {
  return `${chapter.title || chapter.filename || 'chapter'}.txt`
}

function extractOutlinePreview(selectedWork) {
  const outline = selectedWork?.artifacts?.find((item) => item.path.endsWith('outline.md'))
  return outline?.preview || ''
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
  const [passwordForm, setPasswordForm] = useState(emptyPassword)
  const [overview, setOverview] = useState(null)
  const [invites, setInvites] = useState([])
  const [credential, setCredential] = useState(emptyCredential)
  const [savedCredential, setSavedCredential] = useState(null)
  const [connectionPresets, setConnectionPresets] = useState([])
  const [works, setWorks] = useState([])
  const [workForm, setWorkForm] = useState(emptyWork)
  const [selectedWorkId, setSelectedWorkId] = useState('')
  const [selectedWork, setSelectedWork] = useState(null)
  const [selectedChapterId, setSelectedChapterId] = useState('')
  const [selectedChapter, setSelectedChapter] = useState(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [chapterBusy, setChapterBusy] = useState(false)

  const isAdmin = user?.role === 'admin'
  const mustChangePassword = Boolean(user?.must_change_password)

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

  useEffect(() => {
    if (!token || !selectedWorkId || !selectedWork) return
    if (!['starting', 'running'].includes(selectedWork.work.status)) return
    const timer = setInterval(() => {
      loadWork(selectedWorkId).catch((error) => setMessage(error.message))
    }, 3000)
    return () => clearInterval(timer)
  }, [token, selectedWorkId, selectedWork?.work?.status])

  useEffect(() => {
    if (!token || !selectedWorkId || !selectedChapterId) return
    loadChapter(selectedWorkId, selectedChapterId).catch((error) => setMessage(error.message))
  }, [token, selectedWorkId, selectedChapterId])

  useEffect(() => {
    const handler = async (event) => {
      if (!(event.ctrlKey || event.metaKey) || !event.shiftKey || event.key.toLowerCase() !== 'c') return
      if (!selectedChapter?.cleaned_text) return
      event.preventDefault()
      try {
        await navigator.clipboard.writeText(selectedChapter.cleaned_text)
        setMessage(`已复制《${selectedChapter.title}》纯文本`) 
      } catch (error) {
        setMessage(`复制失败：${error.message}`)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [selectedChapter])

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
    if (workList.items.length) {
      setSelectedWorkId((current) => current || workList.items[0].id)
    } else {
      setSelectedWorkId('')
      setSelectedWork(null)
      setSelectedChapterId('')
      setSelectedChapter(null)
    }
    if (me.user.role === 'admin') {
      const [inviteData, presets] = await Promise.all([
        api('/api/invites', {}, token),
        api('/api/testing/connection-presets', {}, token)
      ])
      setInvites(inviteData.items)
      setConnectionPresets(presets)
    } else {
      setInvites([])
      setConnectionPresets([])
    }
  }

  async function loadWork(workId) {
    const detail = await api(`/api/works/${workId}`, {}, token)
    setSelectedWork(detail)
    if (detail.chapters.length) {
      const existing = detail.chapters.find((item) => item.id === selectedChapterId)
      setSelectedChapterId(existing ? existing.id : detail.chapters[0].id)
    } else {
      setSelectedChapterId('')
      setSelectedChapter(null)
    }
  }

  async function loadChapter(workId, chapterId) {
    setChapterBusy(true)
    try {
      const detail = await api(`/api/works/${workId}/chapters/${encodeURIComponent(chapterId)}`, {}, token)
      setSelectedChapter(detail)
    } finally {
      setChapterBusy(false)
    }
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
      setMessage(data.user.must_change_password ? '首次登录，请先修改密码。' : `欢迎回来，${data.user.display_name}`)
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

  async function handlePasswordChange(event) {
    event.preventDefault()
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setMessage('两次输入的新密码不一致')
      return
    }
    setBusy(true)
    try {
      const data = await api('/api/users/me/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: passwordForm.current_password, new_password: passwordForm.new_password })
      }, token)
      setMessage(data.message)
      const currentUsername = user?.username
      const relogin = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username: currentUsername, password: passwordForm.new_password })
      })
      setToken(relogin.token)
      localStorage.setItem('xiaobai-token', relogin.token)
      localStorage.setItem('xiaobai-user', JSON.stringify(relogin.user))
      setUser(relogin.user)
      setPasswordForm(emptyPassword)
      await refreshAll()
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
    setSelectedChapterId('')
    setSelectedChapter(null)
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

  async function copyInviteCode(code) {
    try {
      await navigator.clipboard.writeText(code)
      setMessage(`邀请码 ${code} 已复制`)
    } catch (error) {
      setMessage(`复制邀请码失败：${error.message}`)
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
      setMessage(data.message + (data.model_reply_preview ? ` · 模型回声：${data.model_reply_preview}` : ''))
      const cred = await api('/api/credentials/me', {}, token)
      setSavedCredential(cred.item)
    } catch (error) {
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  function applyConnectionPreset(preset) {
    setCredential({
      provider_alias: preset.provider_alias,
      provider_type: preset.provider_type,
      model_name: preset.model_name,
      reasoning_effort: 'medium',
      base_url: preset.base_url,
      api_key: preset.api_key
    })
    setMessage(`已填入测试连接：${preset.label}`)
  }

  async function createWork(event) {
    event.preventDefault()
    setBusy(true)
    try {
      const payload = {
        ...workForm,
        budget_usd: workForm.budget_usd ? Number(workForm.budget_usd) : null,
        target_chapters: Number(workForm.target_chapters)
      }
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

  async function copyChapterText() {
    if (!selectedChapter?.cleaned_text) return
    try {
      await navigator.clipboard.writeText(selectedChapter.cleaned_text)
      setMessage(`已复制《${selectedChapter.title}》纯文本（快捷键：Ctrl/Cmd+Shift+C）`)
    } catch (error) {
      setMessage(`复制失败：${error.message}`)
    }
  }

  async function downloadChapter() {
    if (!selectedWorkId || !selectedChapterId || !selectedChapter) return
    try {
      await downloadFile(`/api/works/${selectedWorkId}/chapters/${encodeURIComponent(selectedChapterId)}/download.txt`, chapterFileName(selectedChapter), token)
      setMessage(`已下载 ${chapterFileName(selectedChapter)}`)
    } catch (error) {
      setMessage(error.message)
    }
  }

  async function downloadAllChapters() {
    if (!selectedWorkId || !selectedWork) return
    try {
      await downloadFile(`/api/works/${selectedWorkId}/download/all.txt`, `${selectedWork.work.title}-all.txt`, token)
      setMessage(`已下载《${selectedWork.work.title}》全部章节 txt`) 
    } catch (error) {
      setMessage(error.message)
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

  const connectionTone = savedCredential?.last_test_status === 'success' ? 'success' : savedCredential?.last_test_status === 'failed' ? 'danger' : 'muted'
  const chapterCount = selectedWork?.chapters?.length || 0

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
          <p>{user?.display_name}（{isAdmin ? '管理员' : '操作者'}）已登录</p>
          <p className="muted">墨菲验收思路：先卡住风险，再展示状态，再提供可复制、可下载、可追踪的结果。</p>
        </div>
        <div className="actions">
          <button className="secondary" onClick={() => refreshAll().then(() => selectedWorkId && loadWork(selectedWorkId))}>刷新</button>
          <button className="secondary" onClick={logout}>退出</button>
        </div>
      </header>

      {message && <p className="message">{message}</p>}

      {mustChangePassword && (
        <Section title="首次登录强制改密" extra={<StatusPill tone="warning">必须完成</StatusPill>}>
          <form className="form two-cols" onSubmit={handlePasswordChange}>
            <label>当前密码<input type="password" value={passwordForm.current_password} onChange={(e) => setPasswordForm({ ...passwordForm, current_password: e.target.value })} /></label>
            <label>新密码<input type="password" value={passwordForm.new_password} onChange={(e) => setPasswordForm({ ...passwordForm, new_password: e.target.value })} /></label>
            <label className="full">确认新密码<input type="password" value={passwordForm.confirm_password} onChange={(e) => setPasswordForm({ ...passwordForm, confirm_password: e.target.value })} /></label>
            <button disabled={busy}>修改密码并继续</button>
          </form>
        </Section>
      )}

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
            <Section title="邀请码管理" extra={<button onClick={createInvite} disabled={busy || mustChangePassword}>新建邀请码</button>}>
              <div className="invite-list">
                {invites.map((invite) => {
                  const [statusLabel, tone] = formatInviteStatus(invite)
                  return (
                    <div className="list-item" key={invite.id}>
                      <div>
                        <strong>{invite.code}</strong>
                        <div className="muted small">{invite.note || '无备注'} · 创建 {invite.created_at}</div>
                        <div className="muted small">使用 {invite.used_count}/{invite.max_uses} · 过期 {invite.expires_at || '无'}</div>
                      </div>
                      <div className="inline-actions">
                        <StatusPill tone={tone}>{statusLabel}</StatusPill>
                        <button className="secondary" onClick={() => copyInviteCode(invite.code)}>复制</button>
                        {!invite.revoked_at && <button className="secondary" onClick={() => revokeInvite(invite.id)}>作废</button>}
                      </div>
                    </div>
                  )
                })}
                {!invites.length && <p className="muted">还没有邀请码。</p>}
              </div>
            </Section>
          )}

          <Section title="账号安全收口" extra={mustChangePassword ? <StatusPill tone="warning">待改密</StatusPill> : <StatusPill tone="success">已就绪</StatusPill>}>
            <form className="form two-cols compact" onSubmit={handlePasswordChange}>
              <label>当前密码<input type="password" value={passwordForm.current_password} onChange={(e) => setPasswordForm({ ...passwordForm, current_password: e.target.value })} /></label>
              <label>新密码<input type="password" value={passwordForm.new_password} onChange={(e) => setPasswordForm({ ...passwordForm, new_password: e.target.value })} /></label>
              <label className="full">确认新密码<input type="password" value={passwordForm.confirm_password} onChange={(e) => setPasswordForm({ ...passwordForm, confirm_password: e.target.value })} /></label>
              <button disabled={busy}>修改管理员/操作者密码</button>
            </form>
          </Section>

          <Section title="模型凭证设置" extra={<StatusPill tone={connectionTone}>{savedCredential?.last_test_status === 'success' ? '连接成功' : savedCredential?.last_test_status === 'failed' ? '连接失败' : '未测试'}</StatusPill>}>
            {isAdmin && connectionPresets.length > 0 && (
              <div className="preset-grid">
                {connectionPresets.map((preset) => (
                  <button key={preset.label} className="secondary" onClick={() => applyConnectionPreset(preset)}>{preset.label}</button>
                ))}
              </div>
            )}
            <div className="form two-cols compact">
              <label>Provider 别名<input value={credential.provider_alias} onChange={(e) => setCredential({ ...credential, provider_alias: e.target.value })} /></label>
              <label>Provider 类型<input value={credential.provider_type || ''} onChange={(e) => setCredential({ ...credential, provider_type: e.target.value })} placeholder="openai / openrouter / anthropic" /></label>
              <label>模型名<input value={credential.model_name} onChange={(e) => setCredential({ ...credential, model_name: e.target.value })} /></label>
              <label>推理强度<select value={credential.reasoning_effort} onChange={(e) => setCredential({ ...credential, reasoning_effort: e.target.value })}>{['off', 'low', 'medium', 'high', 'xhigh', 'max'].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="full">Base URL<input value={credential.base_url || ''} onChange={(e) => setCredential({ ...credential, base_url: e.target.value })} placeholder="例如 https://token.sensenova.cn/v1" /></label>
              <label className="full">API Key<input type="password" value={credential.api_key} onChange={(e) => setCredential({ ...credential, api_key: e.target.value })} placeholder={savedCredential?.masked_api_key || '输入新的 Key'} /></label>
            </div>
            <div className="actions">
              <button onClick={testCredential} disabled={busy || mustChangePassword || !credential.api_key}>点击连接 IP / 模型测试</button>
              <button onClick={saveCredential} disabled={busy || mustChangePassword || !credential.api_key}>保存凭证</button>
            </div>
            {savedCredential && (
              <div className="subtle-box">
                <p>最近保存：{savedCredential.model_name} · {savedCredential.masked_api_key}</p>
                <p>连接状态：{savedCredential.last_test_status || '未测试'} · {savedCredential.last_test_message || '点击上方按钮可验证连接是否成功'}</p>
                {savedCredential.last_tested_at && <p>最近测试时间：{savedCredential.last_tested_at}</p>}
              </div>
            )}
          </Section>

          <Section title="新建作品（快速开始）">
            <form className="form" onSubmit={createWork}>
              <label>作品名<input value={workForm.title} onChange={(e) => setWorkForm({ ...workForm, title: e.target.value })} /></label>
              <label>一句话创作指令<textarea rows="4" value={workForm.prompt} onChange={(e) => setWorkForm({ ...workForm, prompt: e.target.value })} /></label>
              <div className="form two-cols compact">
                <label>风格<input value={workForm.style} onChange={(e) => setWorkForm({ ...workForm, style: e.target.value })} /></label>
                <label>推进方式<select value={workForm.advance_mode} onChange={(e) => setWorkForm({ ...workForm, advance_mode: e.target.value })}><option value="auto">自动模式</option><option value="review">逐章验收</option></select></label>
                <label>目标章节<input type="number" min="1" value={workForm.target_chapters} onChange={(e) => setWorkForm({ ...workForm, target_chapters: e.target.value })} /></label>
                <label>预算(USD)<input type="number" min="0.1" value={workForm.budget_usd} onChange={(e) => setWorkForm({ ...workForm, budget_usd: e.target.value })} placeholder="可留空" /></label>
              </div>
              <button disabled={busy || mustChangePassword}>创建作品</button>
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

          <Section title="创作工作台" extra={selectedWork && <StatusPill tone={['running', 'starting'].includes(selectedWork.work.status) ? 'success' : selectedWork.work.status === 'failed' ? 'danger' : 'default'}>{selectedWork.work.status}</StatusPill>}>
            {!selectedWork && <p className="muted">请选择一部作品。</p>}
            {selectedWork && (
              <>
                <div className="detail-grid">
                  <div><span>作品</span><strong>{selectedWork.work.title}</strong></div>
                  <div><span>阶段</span><strong>{selectedWork.work.current_phase}</strong></div>
                  <div><span>流程</span><strong>{selectedWork.work.current_flow}</strong></div>
                  <div><span>已完成章节</span><strong>{selectedWork.work.completed_chapters}</strong></div>
                  <div><span>目标章节</span><strong>{selectedWork.work.target_chapters || '未设'}</strong></div>
                  <div><span>推进方式</span><strong>{selectedWork.work.advance_mode}</strong></div>
                </div>
                <p className="muted">快速开始：{selectedWork.work.prompt}</p>
                {selectedWork.work.last_error && <p className="error">错误：{selectedWork.work.last_error}</p>}
                <div className="actions">
                  <button onClick={() => runAction('start')} disabled={busy || mustChangePassword}>开始</button>
                  <button className="secondary" onClick={() => runAction('pause')} disabled={busy || mustChangePassword}>暂停</button>
                  <button className="secondary" onClick={() => runAction('continue')} disabled={busy || mustChangePassword}>继续创作</button>
                  <button className="secondary" onClick={downloadAllChapters} disabled={busy || !chapterCount}>下载所有章节 txt</button>
                </div>
                <div className="subtle-box">
                  <p>章节可实时查看。选中章节后可复制纯文本，快捷键：<code>Ctrl/Cmd + Shift + C</code></p>
                  <p>当前已发现章节：{chapterCount}</p>
                </div>
                <h3>运行记录</h3>
                <div className="timeline">
                  {selectedWork.runs.map((run) => (
                    <div className="list-item" key={run.id}>
                      <div>
                        <strong>{run.id}</strong>
                        <div className="muted">{run.mode} · {run.status} · {run.started_at || '未开始'}</div>
                      </div>
                      {run.container_name && <StatusPill tone="muted">{run.container_name}</StatusPill>}
                    </div>
                  ))}
                  {!selectedWork.runs.length && <p className="muted">还没有运行记录。</p>}
                </div>
              </>
            )}
          </Section>

          <Section title="章节实时浏览 / 复制 / 导出" extra={selectedWork?.chapters?.length ? <StatusPill tone="success">{selectedWork.chapters.length} 章</StatusPill> : <StatusPill tone="muted">暂无章节</StatusPill>}>
            {!selectedWork && <p className="muted">请选择作品后查看章节。</p>}
            {selectedWork && (
              <div className="chapter-layout">
                <div className="chapter-list">
                  {selectedWork.chapters.map((chapter) => (
                    <button key={chapter.id} className={`chapter-item ${selectedChapterId === chapter.id ? 'active' : ''}`} onClick={() => setSelectedChapterId(chapter.id)}>
                      <strong>{chapter.title}</strong>
                      <span>{chapter.filename}</span>
                    </button>
                  ))}
                  {!selectedWork.chapters.length && <p className="muted">运行后，这里会实时出现每一章。</p>}
                </div>
                <div className="chapter-viewer card inset">
                  {chapterBusy && <p className="muted">正在加载章节…</p>}
                  {!chapterBusy && !selectedChapter && <p className="muted">请选择左侧章节。</p>}
                  {!chapterBusy && selectedChapter && (
                    <>
                      <div className="section-head slim">
                        <div>
                          <h3>{selectedChapter.title}</h3>
                          <p className="muted small">{selectedChapter.filename}</p>
                        </div>
                        <div className="inline-actions">
                          <button className="secondary" onClick={copyChapterText}>复制本章全文</button>
                          <button className="secondary" onClick={downloadChapter}>下载该章节 txt</button>
                        </div>
                      </div>
                      <pre className="chapter-text">{selectedChapter.cleaned_text}</pre>
                    </>
                  )}
                </div>
              </div>
            )}
          </Section>

          <Section title="大纲与产物（图形化只读展示）">
            {!selectedWork && <p className="muted">请选择一部作品。</p>}
            {selectedWork && (
              <div className="grid artifact-grid">
                <div className="sub-card">
                  <h3>大纲预览</h3>
                  <pre>{extractOutlinePreview(selectedWork) || '暂无大纲产物'}</pre>
                </div>
                <div className="sub-card">
                  <h3>全部产物索引</h3>
                  <div className="artifact-list compact-list">
                    {selectedWork.artifacts.map((artifact) => (
                      <details className="artifact" key={artifact.path}>
                        <summary>{artifact.path} <span className="muted">({artifact.size} bytes)</span></summary>
                        <pre>{artifact.preview}</pre>
                      </details>
                    ))}
                    {!selectedWork.artifacts.length && <p className="muted">暂无产物。</p>}
                  </div>
                </div>
              </div>
            )}
          </Section>
        </div>
      </div>
    </main>
  )
}
