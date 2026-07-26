import { useEffect, useMemo, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || ''

const emptyCredential = {
  provider_alias: 'openai',
  provider_type: 'openai',
  model_name: '',
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

const emptyPassword = { current_password: '', new_password: '', confirm_password: '' }

const STATUS_META = {
  idle: ['未开始', 'neutral'],
  starting: ['启动中', 'warning'],
  running: ['创作中', 'live'],
  paused: ['已暂停', 'warning'],
  completed: ['已完成', 'success'],
  failed: ['运行失败', 'danger'],
  quota_stop: ['额度暂停', 'warning']
}

function formatApiError(data, status) {
  if (!data) return `请求失败（${status}）`
  if (typeof data === 'string') return data
  if (Array.isArray(data)) return data.map((item) => formatApiError(item, status)).join('；')
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => {
      if (typeof item === 'string') return item
      const location = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : ''
      const text = item.msg || item.message || JSON.stringify(item)
      return location ? `${location}：${text}` : text
    }).join('；')
  }
  if (typeof data.detail === 'string') return data.detail
  if (typeof data.message === 'string') return data.message
  return `请求失败（${status}）`
}

async function api(path, options = {}, token) {
  const headers = { ...(options.headers || {}) }
  if (!(options.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  } catch {
    throw new Error('无法连接服务器，请检查网络后重试')
  }
  const contentType = response.headers.get('content-type') || ''
  const text = await response.text()
  let data = text
  if (contentType.includes('application/json') && text) {
    try { data = JSON.parse(text) } catch { data = text }
  }
  if (!response.ok) {
    const error = new Error(formatApiError(data, response.status))
    error.status = response.status
    throw error
  }
  return data
}

async function downloadFile(path, filename, token) {
  const response = await fetch(`${API_BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `下载失败（${response.status}）`)
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

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
  }).format(date)
}

function formatNumber(value) {
  return new Intl.NumberFormat('zh-CN').format(Number(value || 0))
}

function statusInfo(status) {
  return STATUS_META[status] || [status || '未知', 'neutral']
}

function StatusPill({ status, children, tone }) {
  const meta = statusInfo(status)
  return <span className={`status-pill tone-${tone || meta[1]}`}>{children || meta[0]}</span>
}

function Icon({ name, size = 18 }) {
  const paths = {
    book: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H13v15h4.5a2.5 2.5 0 0 1 2.5 2.5z"/></>,
    spark: <><path d="m12 3-1.4 3.6L7 8l3.6 1.4L12 13l1.4-3.6L17 8l-3.6-1.4z"/><path d="m5 14-.8 2.2L2 17l2.2.8L5 20l.8-2.2L8 17l-2.2-.8z"/></>,
    model: <><rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8 9h8M8 13h5M8 17h3"/></>,
    users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
    plus: <><path d="M12 5v14M5 12h14"/></>,
    play: <path d="m8 5 11 7-11 7z"/>,
    pause: <><path d="M9 5v14M15 5v14"/></>,
    arrow: <path d="m9 18 6-6-6-6"/>,
    copy: <><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></>,
    download: <><path d="M12 3v12M7 10l5 5 5-5"/><path d="M5 21h14"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    alert: <><path d="M12 3 2.5 20h19z"/><path d="M12 9v4M12 17h.01"/></>,
    refresh: <><path d="M20 11a8 8 0 1 0-2.34 5.66"/><path d="M20 4v7h-7"/></>,
    logout: <><path d="M10 17l5-5-5-5M15 12H3"/><path d="M15 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/></>
  }
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

function SectionHeader({ eyebrow, title, description, action }) {
  return (
    <div className="section-header">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action && <div className="section-action">{action}</div>}
    </div>
  )
}

function EngineNotice({ health }) {
  const loading = !health
  const isMock = health?.engine_mode === 'mock'
  const offline = Boolean(health && !health.ok)
  return (
    <div className={`engine-notice ${offline ? 'notice-danger' : isMock || loading ? 'notice-warning' : 'notice-success'}`}>
      <Icon name={offline || isMock || loading ? 'alert' : 'check'} />
      <div>
        <strong>{loading ? '正在确认引擎状态' : offline ? '服务连接异常' : isMock ? '当前为模拟验收模式' : '真实小说引擎已连接'}</strong>
        <span>{loading ? '状态确认完成前不会提交创作任务。' : offline ? '暂时无法确认后端状态，请不要重复提交任务。' : isMock ? '只生成演示文本，不会调用大模型，也不代表正式小说质量。' : '新任务将调用 ainovel 与你已验证的模型配置。'}</span>
      </div>
    </div>
  )
}

function ProgressBar({ current, target }) {
  const safeTarget = Math.max(Number(target || 0), 1)
  const percent = Math.min(100, Math.round((Number(current || 0) / safeTarget) * 100))
  return <div className="progress-track"><span style={{ width: `${percent}%` }} /></div>
}

function LoginView({ health, busy, message, onLogin, onClaim }) {
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [claimForm, setClaimForm] = useState({ code: '', username: '', display_name: '', password: '' })
  return (
    <main className="auth-shell">
      <section className="auth-intro">
        <div className="brand-mark"><Icon name="spark" size={24} /></div>
        <span className="eyebrow">AI NOVEL STUDIO</span>
        <h1>让创作过程<br />清楚、安静、可控。</h1>
        <p>小白一号把模型连接、长篇生成、章节校对与纯文本导出收进一个工作台。</p>
        <EngineNotice health={health} />
        <div className="auth-footnote">邀请制访问 · 独立运行空间 · 章节实时保存</div>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <span className="eyebrow">欢迎回来</span>
          <h2>登录创作空间</h2>
          <form onSubmit={(event) => { event.preventDefault(); onLogin(loginForm) }}>
            <label>用户名<input autoComplete="username" value={loginForm.username} onChange={(event) => setLoginForm({ ...loginForm, username: event.target.value })} placeholder="请输入用户名" /></label>
            <label>密码<input type="password" autoComplete="current-password" value={loginForm.password} onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })} placeholder="请输入密码" /></label>
            <button className="button primary wide" disabled={busy || !loginForm.username || !loginForm.password}>登录</button>
          </form>
          <details className="claim-box">
            <summary>第一次使用？使用邀请码领取账号</summary>
            <form onSubmit={(event) => { event.preventDefault(); onClaim(claimForm, () => setClaimForm({ code: '', username: '', display_name: '', password: '' })) }}>
              <label>邀请码<input value={claimForm.code} onChange={(event) => setClaimForm({ ...claimForm, code: event.target.value })} /></label>
              <div className="field-row">
                <label>用户名<input autoComplete="username" value={claimForm.username} onChange={(event) => setClaimForm({ ...claimForm, username: event.target.value })} /></label>
                <label>显示名<input value={claimForm.display_name} onChange={(event) => setClaimForm({ ...claimForm, display_name: event.target.value })} /></label>
              </div>
              <label>初始密码<input type="password" autoComplete="new-password" value={claimForm.password} onChange={(event) => setClaimForm({ ...claimForm, password: event.target.value })} /></label>
              <button className="button secondary wide" disabled={busy}>领取账号</button>
            </form>
          </details>
          {message && <div className="inline-message">{message}</div>}
        </div>
      </section>
    </main>
  )
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [token, setToken] = useState(localStorage.getItem('xiaobai-token') || '')
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('xiaobai-user') || 'null') } catch { return null }
  })
  const [activeView, setActiveView] = useState('studio')
  const [overview, setOverview] = useState(null)
  const [invites, setInvites] = useState([])
  const [inviteForm, setInviteForm] = useState({ note: '', expires_in_hours: 72, max_uses: 1 })
  const [credential, setCredential] = useState(emptyCredential)
  const [savedCredential, setSavedCredential] = useState(null)
  const [connectionPresets, setConnectionPresets] = useState([])
  const [works, setWorks] = useState([])
  const [workForm, setWorkForm] = useState(emptyWork)
  const [showCreateWork, setShowCreateWork] = useState(false)
  const [selectedWorkId, setSelectedWorkId] = useState('')
  const [selectedWork, setSelectedWork] = useState(null)
  const [selectedChapterId, setSelectedChapterId] = useState('')
  const [selectedChapter, setSelectedChapter] = useState(null)
  const [followLatest, setFollowLatest] = useState(true)
  const [passwordForm, setPasswordForm] = useState(emptyPassword)
  const [message, setMessage] = useState('')
  const [messageTone, setMessageTone] = useState('info')
  const [busy, setBusy] = useState(false)
  const [chapterBusy, setChapterBusy] = useState(false)

  const isAdmin = user?.role === 'admin'
  const mustChangePassword = Boolean(user?.must_change_password)
  const isRealEngine = health?.engine_mode === 'ainovel'

  function notify(text, tone = 'info') {
    setMessage(text)
    setMessageTone(tone)
  }

  async function refreshHealth() {
    try { setHealth(await api('/api/health')) } catch { setHealth({ ok: false, engine_mode: 'unknown' }) }
  }

  useEffect(() => {
    refreshHealth()
    const timer = setInterval(refreshHealth, 30000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!token) return
    refreshAll().catch((error) => {
      if (error.status === 401) logout()
      else notify(error.message, 'danger')
    })
  }, [token])

  useEffect(() => {
    if (!token || !selectedWorkId) return
    loadWork(selectedWorkId, true).catch((error) => notify(error.message, 'danger'))
  }, [selectedWorkId, token])

  useEffect(() => {
    if (!token || !selectedWorkId || !selectedWork) return
    if (!['starting', 'running'].includes(selectedWork.work.status)) return
    const timer = setInterval(() => {
      loadWork(selectedWorkId, true).catch((error) => notify(error.message, 'danger'))
    }, 2500)
    return () => clearInterval(timer)
  }, [token, selectedWorkId, selectedWork?.work?.status, selectedChapterId, followLatest])

  useEffect(() => {
    const handler = async (event) => {
      if (!(event.ctrlKey || event.metaKey) || !event.shiftKey || event.key.toLowerCase() !== 'c') return
      if (!selectedChapter?.cleaned_text) return
      event.preventDefault()
      try {
        await navigator.clipboard.writeText(selectedChapter.cleaned_text)
        notify(`已复制《${selectedChapter.title}》全文`, 'success')
      } catch { notify('复制失败，请检查浏览器剪贴板权限', 'danger') }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [selectedChapter])

  async function refreshAll() {
    const me = await api('/api/me', {}, token)
    setUser(me.user)
    localStorage.setItem('xiaobai-user', JSON.stringify(me.user))
    if (me.user.must_change_password) {
      setActiveView('account')
      return
    }
    const [system, cred, workList] = await Promise.all([
      api('/api/system/overview', {}, token),
      api('/api/credentials/me', {}, token),
      api('/api/works', {}, token)
    ])
    setOverview(system)
    setSavedCredential(cred.item)
    setWorks(workList.items)
    if (cred.item) {
      setCredential((current) => ({
        provider_alias: cred.item.provider_alias,
        provider_type: cred.item.provider_type || 'openai',
        model_name: cred.item.model_name,
        reasoning_effort: cred.item.reasoning_effort,
        base_url: cred.item.base_url || '',
        api_key: current.api_key
      }))
    }
    if (workList.items.length) setSelectedWorkId((current) => current || workList.items[0].id)
    else {
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

  async function loadWork(workId, refreshChapter = false) {
    const detail = await api(`/api/works/${workId}`, {}, token)
    setSelectedWork(detail)
    setWorks((items) => items.map((item) => item.id === workId ? { ...item, ...detail.work } : item))
    const chapters = detail.chapters || []
    if (!chapters.length) {
      setSelectedChapterId('')
      setSelectedChapter(null)
      return
    }
    const existing = chapters.find((item) => item.id === selectedChapterId)
    const chosen = followLatest ? chapters[chapters.length - 1] : (existing || chapters[chapters.length - 1])
    if (!existing) setFollowLatest(true)
    setSelectedChapterId(chosen.id)
    if (refreshChapter || chosen.id !== selectedChapterId) await loadChapter(workId, chosen.id, false)
  }

  async function loadChapter(workId, chapterId, showLoader = true) {
    if (showLoader) setChapterBusy(true)
    try {
      const detail = await api(`/api/works/${workId}/chapters/${encodeURIComponent(chapterId)}`, {}, token)
      setSelectedChapter(detail)
    } finally {
      if (showLoader) setChapterBusy(false)
    }
  }

  async function handleLogin(form) {
    setBusy(true)
    try {
      const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify(form) })
      setToken(data.token)
      setUser(data.user)
      localStorage.setItem('xiaobai-token', data.token)
      localStorage.setItem('xiaobai-user', JSON.stringify(data.user))
      notify(data.user.must_change_password ? '首次登录，请先设置新密码' : `欢迎回来，${data.user.display_name}`, 'success')
      if (data.user.must_change_password) setActiveView('account')
    } catch (error) { notify(error.message, 'danger') } finally { setBusy(false) }
  }

  async function handleClaim(form, reset) {
    setBusy(true)
    try {
      const data = await api('/api/auth/claim', { method: 'POST', body: JSON.stringify(form) })
      notify(`${data.message}，现在可以登录`, 'success')
      reset()
    } catch (error) { notify(error.message, 'danger') } finally { setBusy(false) }
  }

  function logout() {
    localStorage.removeItem('xiaobai-token')
    localStorage.removeItem('xiaobai-user')
    setToken('')
    setUser(null)
    setOverview(null)
    setSelectedWork(null)
    setSelectedChapter(null)
    setMessage('')
  }

  async function createWork(event) {
    event.preventDefault()
    setBusy(true)
    try {
      const payload = {
        ...workForm,
        target_chapters: Number(workForm.target_chapters),
        budget_usd: workForm.budget_usd ? Number(workForm.budget_usd) : null
      }
      const data = await api('/api/works', { method: 'POST', body: JSON.stringify(payload) }, token)
      notify(data.message, 'success')
      setWorkForm(emptyWork)
      setShowCreateWork(false)
      const list = await api('/api/works', {}, token)
      setWorks(list.items)
      if (list.items.length) setSelectedWorkId(list.items[0].id)
    } catch (error) { notify(error.message, 'danger') } finally { setBusy(false) }
  }

  async function runAction(action) {
    if (!selectedWorkId) return
    setBusy(true)
    try {
      const data = await api(`/api/works/${selectedWorkId}/runs/${action}`, { method: 'POST' }, token)
      notify(data.message, 'success')
      await loadWork(selectedWorkId, true)
      const list = await api('/api/works', {}, token)
      setWorks(list.items)
    } catch (error) { notify(error.message, 'danger') } finally { setBusy(false) }
  }

  async function selectChapter(chapter, chapters) {
    setSelectedChapterId(chapter.id)
    setFollowLatest(chapter.id === chapters[chapters.length - 1]?.id)
    try { await loadChapter(selectedWorkId, chapter.id) } catch (error) { notify(error.message, 'danger') }
  }

  async function copyChapterText() {
    if (!selectedChapter?.cleaned_text) return
    try {
      await navigator.clipboard.writeText(selectedChapter.cleaned_text)
      notify(`已复制《${selectedChapter.title}》全文`, 'success')
    } catch { notify('复制失败，请检查浏览器剪贴板权限', 'danger') }
  }

  async function downloadChapter() {
    if (!selectedChapter) return
    try {
      await downloadFile(`/api/works/${selectedWorkId}/chapters/${encodeURIComponent(selectedChapter.id)}/download.txt`, `${selectedChapter.title}.txt`, token)
      notify('章节 txt 已下载', 'success')
    } catch (error) { notify(error.message, 'danger') }
  }

  async function downloadAllChapters() {
    if (!selectedWork) return
    try {
      await downloadFile(`/api/works/${selectedWorkId}/download/all.txt`, `${selectedWork.work.title}-all.txt`, token)
      notify('全书 txt 已下载', 'success')
    } catch (error) { notify(error.message, 'danger') }
  }

  async function saveCredential(event) {
    event.preventDefault()
    setBusy(true)
    try {
      const data = await api('/api/credentials/me', { method: 'PUT', body: JSON.stringify(credential) }, token)
      notify(`${data.message}；请继续执行连接测试`, 'success')
      const current = await api('/api/credentials/me', {}, token)
      setSavedCredential(current.item)
    } catch (error) { notify(error.message, 'danger') } finally { setBusy(false) }
  }

  async function testCredential() {
    setBusy(true)
    try {
      const data = await api('/api/credentials/test', { method: 'POST', body: JSON.stringify(credential) }, token)
      notify(data.message, data.ok ? 'success' : 'danger')
      const current = await api('/api/credentials/me', {}, token)
      setSavedCredential(current.item)
      if (current.item?.last_test_status === 'success') setCredential((value) => ({ ...value, api_key: '' }))
    } catch (error) { notify(error.message, 'danger') } finally { setBusy(false) }
  }

  function applyConnectionPreset(preset) {
    setCredential((current) => ({
      ...current,
      provider_alias: preset.provider_alias,
      provider_type: preset.provider_type,
      model_name: preset.model_name,
      base_url: preset.base_url
    }))
    notify(`${preset.label} 的公开参数已填入，请输入自己的 API Key`, 'info')
  }

  async function createInvite(event) {
    event.preventDefault()
    setBusy(true)
    try {
      await api('/api/invites', { method: 'POST', body: JSON.stringify({ ...inviteForm, expires_in_hours: Number(inviteForm.expires_in_hours), max_uses: Number(inviteForm.max_uses) }) }, token)
      setInvites((await api('/api/invites', {}, token)).items)
      setInviteForm({ note: '', expires_in_hours: 72, max_uses: 1 })
      notify('邀请码已创建', 'success')
    } catch (error) { notify(error.message, 'danger') } finally { setBusy(false) }
  }

  async function revokeInvite(id) {
    setBusy(true)
    try {
      await api(`/api/invites/${id}/revoke`, { method: 'POST' }, token)
      setInvites((await api('/api/invites', {}, token)).items)
      notify('邀请码已作废', 'success')
    } catch (error) { notify(error.message, 'danger') } finally { setBusy(false) }
  }

  async function copyText(text, label) {
    try { await navigator.clipboard.writeText(text); notify(`${label}已复制`, 'success') }
    catch { notify('复制失败，请检查浏览器权限', 'danger') }
  }

  async function changePassword(event) {
    event.preventDefault()
    if (passwordForm.new_password !== passwordForm.confirm_password) return notify('两次输入的新密码不一致', 'danger')
    setBusy(true)
    try {
      const result = await api('/api/users/me/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: passwordForm.current_password, new_password: passwordForm.new_password })
      }, token)
      const relogin = await api('/api/auth/login', {
        method: 'POST', body: JSON.stringify({ username: user.username, password: passwordForm.new_password })
      })
      setToken(relogin.token)
      setUser(relogin.user)
      localStorage.setItem('xiaobai-token', relogin.token)
      localStorage.setItem('xiaobai-user', JSON.stringify(relogin.user))
      setPasswordForm(emptyPassword)
      notify(result.message, 'success')
      setActiveView('studio')
    } catch (error) { notify(error.message, 'danger') } finally { setBusy(false) }
  }

  const navItems = useMemo(() => [
    ['studio', 'book', '创作工作台'],
    ['model', 'model', '模型连接'],
    ...(isAdmin ? [['admin', 'users', '邀请与系统']] : []),
    ['account', 'user', '账号安全']
  ], [isAdmin])

  if (!token) return <LoginView health={health} busy={busy} message={message} onLogin={handleLogin} onClaim={handleClaim} />

  const work = selectedWork?.work
  const chapters = selectedWork?.chapters || []
  const latestChapter = chapters[chapters.length - 1]
  const canStart = work?.status === 'idle'
  const canPause = ['starting', 'running'].includes(work?.status)
  const canContinue = ['paused', 'failed', 'quota_stop'].includes(work?.status)
  const credentialReady = savedCredential?.last_test_status === 'success'
  const startBlocked = isRealEngine && !credentialReady

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark small-mark"><Icon name="spark" /></span><div><strong>小白一号</strong><span>Novel Studio</span></div></div>
        <nav>
          {navItems.map(([id, icon, label]) => (
            <button key={id} className={`nav-item ${activeView === id ? 'active' : ''}`} onClick={() => setActiveView(id)}>
              <Icon name={icon} /><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="user-chip"><span>{user?.display_name?.slice(0, 1) || 'U'}</span><div><strong>{user?.display_name}</strong><small>{isAdmin ? '管理员' : '创作者'}</small></div></div>
          <button className="nav-item" onClick={logout}><Icon name="logout" /><span>退出登录</span></button>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">{activeView === 'studio' ? 'WRITING DESK' : activeView === 'model' ? 'MODEL SETTINGS' : activeView === 'admin' ? 'ADMINISTRATION' : 'ACCOUNT'}</span></div>
          <div className="topbar-status"><span className={`health-dot ${health?.ok ? 'online' : ''}`} />{!health ? '状态确认中' : health.ok ? '服务正常' : '连接异常'} · {!health ? '引擎确认中' : isRealEngine ? '真实引擎' : health.engine_mode === 'mock' ? '模拟引擎' : '引擎未知'}</div>
        </header>

        {message && <div className={`toast toast-${messageTone}`}><span>{message}</span><button aria-label="关闭提示" onClick={() => setMessage('')}>×</button></div>}
        {mustChangePassword && activeView !== 'account' && <div className="forced-banner"><Icon name="alert" /><span>首次登录必须先修改密码，其他功能暂不可用。</span><button className="text-button" onClick={() => setActiveView('account')}>立即修改</button></div>}

        {activeView === 'studio' && !mustChangePassword && (
          <div className="view studio-view">
            <SectionHeader eyebrow="创作空间" title="把注意力留给故事。" description="创建作品、观察生成进度，并在同一处阅读全文。" action={<button className="button primary" onClick={() => setShowCreateWork(!showCreateWork)}><Icon name="plus" />新建作品</button>} />
            <EngineNotice health={health} />

            {showCreateWork && (
              <form className="panel create-panel" onSubmit={createWork}>
                <div className="panel-title"><div><span className="eyebrow">NEW PROJECT</span><h3>开始一部新作品</h3></div><button type="button" className="icon-button" onClick={() => setShowCreateWork(false)}>×</button></div>
                <div className="field-row">
                  <label>作品名<input value={workForm.title} onChange={(event) => setWorkForm({ ...workForm, title: event.target.value })} placeholder="例如：雾港来信" /></label>
                  <label>目标章节数<input type="number" min="1" max="10000" value={workForm.target_chapters} onChange={(event) => setWorkForm({ ...workForm, target_chapters: event.target.value })} /></label>
                </div>
                <label>故事设定与创作要求<textarea rows="5" value={workForm.prompt} onChange={(event) => setWorkForm({ ...workForm, prompt: event.target.value })} placeholder="写清主角、世界、冲突、风格和你不希望出现的内容。输入越明确，首轮结果越稳定。" /></label>
                <details className="advanced-fields">
                  <summary>高级记录项</summary>
                  <div className="field-row">
                    <label>风格标识<input value={workForm.style} onChange={(event) => setWorkForm({ ...workForm, style: event.target.value })} /></label>
                    <label>预算备注（美元）<input type="number" min="0.01" step="0.01" value={workForm.budget_usd} onChange={(event) => setWorkForm({ ...workForm, budget_usd: event.target.value })} placeholder="仅记录，暂不自动计费" /></label>
                  </div>
                  <p className="helper-text">当前版本只支持自动推进；预算字段仅用于作品记录，不会自动熔断。</p>
                </details>
                <div className="form-actions"><button type="button" className="button ghost" onClick={() => setShowCreateWork(false)}>取消</button><button className="button primary" disabled={busy || !workForm.title.trim() || !workForm.prompt.trim()}>创建作品</button></div>
              </form>
            )}

            <div className="studio-grid">
              <aside className="project-panel panel">
                <div className="panel-title"><div><span className="eyebrow">PROJECTS</span><h3>我的作品</h3></div><span className="count-badge">{works.length}</span></div>
                <div className="project-list">
                  {works.map((item) => {
                    const [label, tone] = statusInfo(item.status)
                    return <button key={item.id} className={`project-item ${selectedWorkId === item.id ? 'active' : ''}`} onClick={() => { setSelectedWorkId(item.id); setFollowLatest(true) }}>
                      <div><strong>{item.title}</strong><span>{formatDate(item.updated_at)}</span></div>
                      <div className="project-meta"><StatusPill tone={tone}>{label}</StatusPill><span>{item.completed_chapters}/{item.target_chapters || '∞'} 章</span></div>
                    </button>
                  })}
                  {!works.length && <div className="empty-state compact"><Icon name="book" size={28} /><strong>还没有作品</strong><span>从右上角“新建作品”开始。</span></div>}
                </div>
              </aside>

              <section className="story-panel">
                {!work && <div className="panel empty-state"><Icon name="book" size={34} /><h3>选择一部作品</h3><p>作品的状态、章节与运行记录会显示在这里。</p></div>}
                {work && <>
                  <div className="panel story-overview">
                    <div className="story-heading">
                      <div><span className="eyebrow">CURRENT PROJECT</span><h2>{work.title}</h2><p>{work.prompt}</p></div>
                      <StatusPill status={work.status} />
                    </div>
                    <div className="progress-summary">
                      <div><strong>{formatNumber(work.completed_chapters)}</strong><span>已生成章节</span></div>
                      <div><strong>{work.target_chapters || '∞'}</strong><span>阶段目标</span></div>
                      <div><strong>{work.current_phase}</strong><span>当前阶段</span></div>
                      <div><strong>{isRealEngine ? '真实' : '模拟'}</strong><span>运行类型</span></div>
                    </div>
                    <ProgressBar current={work.completed_chapters} target={work.target_chapters} />
                    {work.last_error && <div className="error-box"><Icon name="alert" /><div><strong>最近一次运行失败</strong><pre>{work.last_error}</pre></div></div>}
                    {startBlocked && canStart && <div className="soft-warning">真实生成前需要先在“模型连接”中保存并测试凭证。</div>}
                    <div className="run-actions">
                      <button className="button primary" disabled={busy || !canStart || startBlocked} onClick={() => runAction('start')}><Icon name="play" />{isRealEngine ? '开始生成小说' : '运行模拟验收'}</button>
                      <button className="button secondary" disabled={busy || !canPause} onClick={() => runAction('pause')}><Icon name="pause" />暂停</button>
                      <button className="button secondary" disabled={busy || !canContinue || startBlocked} onClick={() => runAction('continue')}><Icon name="arrow" />继续创作</button>
                      <button className="button ghost" onClick={() => loadWork(selectedWorkId, true)}><Icon name="refresh" />刷新</button>
                      <button className="button ghost" disabled={!chapters.length} onClick={downloadAllChapters}><Icon name="download" />导出全书</button>
                    </div>
                  </div>

                  <div className="reader panel">
                    <div className="reader-sidebar">
                      <div className="reader-list-head"><div><span className="eyebrow">CHAPTERS</span><h3>章节</h3></div><span>{chapters.length}</span></div>
                      <div className="chapter-list">
                        {chapters.map((chapter) => <button key={chapter.id} className={`chapter-item ${selectedChapterId === chapter.id ? 'active' : ''}`} onClick={() => selectChapter(chapter, chapters)}>
                          <span className="chapter-index">{String(chapter.index || '·').padStart(2, '0')}</span>
                          <span className="chapter-label"><strong>{chapter.title}</strong><small>{formatNumber(chapter.character_count)} 字符 · {chapter.paragraph_count} 段</small></span>
                        </button>)}
                        {!chapters.length && <div className="empty-state compact"><span>运行开始后，章节会实时出现在这里。</span></div>}
                      </div>
                    </div>
                    <article className="reader-content">
                      {chapterBusy && <div className="reader-loading">正在读取章节…</div>}
                      {!chapterBusy && !selectedChapter && <div className="empty-state"><Icon name="book" size={32} /><h3>暂无正文</h3><p>开始生成后，完整章节会在这里持续刷新。</p></div>}
                      {!chapterBusy && selectedChapter && <>
                        <header className="chapter-header">
                          <div><span className="eyebrow">{followLatest && selectedChapter.id === latestChapter?.id && ['starting', 'running'].includes(work.status) ? 'LIVE · 实时刷新' : `CHAPTER ${selectedChapter.index || ''}`}</span><h1>{selectedChapter.title}</h1><p>{formatNumber(selectedChapter.character_count)} 字符 · {selectedChapter.paragraph_count} 段 · 更新于 {formatDate(selectedChapter.updated_at)}</p></div>
                          <div className="reader-actions"><button className="icon-action" onClick={copyChapterText} title="复制全文" aria-label="复制本章全文"><Icon name="copy" /></button><button className="icon-action" onClick={downloadChapter} title="下载本章" aria-label="下载本章文本"><Icon name="download" /></button></div>
                        </header>
                        <div className="chapter-body">{selectedChapter.cleaned_text}</div>
                      </>}
                    </article>
                  </div>

                  <details className="panel details-panel">
                    <summary>运行记录与原始产物</summary>
                    <div className="details-grid">
                      <section><h4>运行记录</h4>{selectedWork.runs.map((run) => <div className="run-row" key={run.id}><div><strong>{run.id}</strong><span>{run.mode === 'ainovel' ? '真实引擎' : '模拟引擎'} · {formatDate(run.started_at)}</span></div><StatusPill status={run.status} /></div>)}{!selectedWork.runs.length && <p className="muted">暂无运行记录</p>}</section>
                      <section><h4>产物索引</h4>{selectedWork.artifacts.map((artifact) => <details className="artifact-row" key={artifact.path}><summary><span>{artifact.path}</span><small>{formatNumber(artifact.size)} B</small></summary><pre>{artifact.preview}</pre></details>)}{!selectedWork.artifacts.length && <p className="muted">暂无产物</p>}</section>
                    </div>
                  </details>
                </>}
              </section>
            </div>
          </div>
        )}

        {activeView === 'model' && !mustChangePassword && (
          <div className="view narrow-view">
            <SectionHeader eyebrow="模型连接" title="只在验证成功后开始创作。" description="连接状态与已保存配置严格绑定，修改任一参数后必须重新测试。" />
            <EngineNotice health={health} />
            <div className="panel credential-status">
              <div><span className={`connection-orb ${credentialReady ? 'ready' : savedCredential?.last_test_status === 'failed' ? 'failed' : ''}`} /><div><span className="eyebrow">SAVED CONNECTION</span><h3>{savedCredential ? `${savedCredential.provider_alias} / ${savedCredential.model_name}` : '尚未保存模型配置'}</h3><p>{savedCredential?.last_test_message || '保存配置后执行一次真实连接测试。'}</p></div></div>
              <StatusPill tone={credentialReady ? 'success' : savedCredential?.last_test_status === 'failed' ? 'danger' : 'neutral'}>{credentialReady ? '已验证' : savedCredential?.last_test_status === 'failed' ? '验证失败' : '未验证'}</StatusPill>
            </div>
            {connectionPresets.length > 0 && <div className="preset-row"><span>公开参数模板</span>{connectionPresets.map((preset) => <button className="preset-button" key={preset.label} onClick={() => applyConnectionPreset(preset)}>{preset.label}</button>)}</div>}
            <form className="panel model-form" onSubmit={saveCredential}>
              <div className="field-row three-fields">
                <label>服务别名<input value={credential.provider_alias} onChange={(event) => setCredential({ ...credential, provider_alias: event.target.value })} /></label>
                <label>兼容类型<select value={credential.provider_type || 'openai'} onChange={(event) => setCredential({ ...credential, provider_type: event.target.value })}><option value="openai">OpenAI Compatible</option><option value="openrouter">OpenRouter</option><option value="deepseek">DeepSeek</option><option value="qwen">Qwen</option><option value="glm">GLM</option></select></label>
                <label>推理强度<select value={credential.reasoning_effort} onChange={(event) => setCredential({ ...credential, reasoning_effort: event.target.value })}><option value="off">关闭</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="xhigh">XHigh</option><option value="max">Max</option></select></label>
              </div>
              <label>Base URL<input value={credential.base_url} onChange={(event) => setCredential({ ...credential, base_url: event.target.value })} placeholder="https://example.com/v1" /></label>
              <label>模型名称<input value={credential.model_name} onChange={(event) => setCredential({ ...credential, model_name: event.target.value })} placeholder="填写服务端实际支持的模型名" /></label>
              <label>API Key<input type="password" autoComplete="off" value={credential.api_key} onChange={(event) => setCredential({ ...credential, api_key: event.target.value })} placeholder={savedCredential ? `重新输入以保存或测试（已保存 ${savedCredential.masked_api_key}）` : '输入 API Key'} /></label>
              <div className="security-note"><Icon name="alert" /><span>API Key 不会在页面回显。点击“保存配置”会使旧测试状态失效；随后请用同一组参数点击“测试连接”。</span></div>
              <div className="form-actions"><button type="button" className="button secondary" disabled={busy || !credential.api_key || !credential.base_url || !credential.model_name} onClick={testCredential}>测试连接</button><button className="button primary" disabled={busy || !credential.api_key || !credential.base_url || !credential.model_name}>保存配置</button></div>
            </form>
          </div>
        )}

        {activeView === 'admin' && isAdmin && !mustChangePassword && (
          <div className="view narrow-view">
            <SectionHeader eyebrow="管理" title="邀请与运行边界。" description="账号采用邀请码领取；活跃任务受全站与单用户上限保护。" />
            <div className="metric-grid">
              <div className="metric-card"><span>我的作品</span><strong>{overview?.work_count || 0}</strong></div>
              <div className="metric-card"><span>有效邀请记录</span><strong>{overview?.invite_count || 0}</strong></div>
              <div className="metric-card"><span>我的活跃任务</span><strong>{overview?.active_runs_for_user || 0}/{overview?.limits?.per_operator || 0}</strong></div>
              <div className="metric-card"><span>全站活跃任务</span><strong>{overview?.active_runs_global || 0}/{overview?.limits?.global || 0}</strong></div>
            </div>
            <form className="panel invite-form" onSubmit={createInvite}>
              <div className="panel-title"><div><span className="eyebrow">NEW INVITE</span><h3>创建邀请码</h3></div></div>
              <div className="field-row three-fields">
                <label>备注<input value={inviteForm.note} onChange={(event) => setInviteForm({ ...inviteForm, note: event.target.value })} placeholder="发给谁" /></label>
                <label>有效时长（小时）<input type="number" min="1" max="720" value={inviteForm.expires_in_hours} onChange={(event) => setInviteForm({ ...inviteForm, expires_in_hours: event.target.value })} /></label>
                <label>可使用次数<input type="number" min="1" max="1000" value={inviteForm.max_uses} onChange={(event) => setInviteForm({ ...inviteForm, max_uses: event.target.value })} /></label>
              </div>
              <div className="form-actions"><button className="button primary" disabled={busy}><Icon name="plus" />创建邀请码</button></div>
            </form>
            <div className="panel invite-list-panel">
              <div className="panel-title"><div><span className="eyebrow">INVITES</span><h3>邀请码记录</h3></div><span className="count-badge">{invites.length}</span></div>
              <div className="invite-table">
                {invites.map((invite) => {
                  const expired = invite.expires_at && new Date(invite.expires_at).getTime() < Date.now()
                  const exhausted = invite.used_count >= invite.max_uses
                  const inactive = invite.revoked_at || expired || exhausted
                  return <div className="invite-row" key={invite.id}>
                    <div className="invite-code"><code>{invite.code}</code><button className="icon-action small" aria-label="复制邀请码" title="复制邀请码" onClick={() => copyText(invite.code, '邀请码')}><Icon name="copy" size={15} /></button></div>
                    <div><strong>{invite.note || '无备注'}</strong><span>创建 {formatDate(invite.created_at)} · 到期 {formatDate(invite.expires_at)}</span></div>
                    <span>{invite.used_count}/{invite.max_uses} 次</span>
                    <StatusPill tone={inactive ? 'neutral' : 'success'}>{invite.revoked_at ? '已作废' : expired ? '已过期' : exhausted ? '已用完' : '可领取'}</StatusPill>
                    <button className="text-button danger-text" disabled={Boolean(invite.revoked_at)} onClick={() => revokeInvite(invite.id)}>作废</button>
                  </div>
                })}
                {!invites.length && <div className="empty-state compact">暂无邀请码</div>}
              </div>
            </div>
          </div>
        )}

        {activeView === 'account' && (
          <div className="view account-view">
            <SectionHeader eyebrow="账号安全" title={mustChangePassword ? '先设置一个新密码。' : '保护你的创作空间。'} description={mustChangePassword ? '这是首次登录的必要步骤，完成后才能进入工作台。' : '定期更新密码，不要与其他服务重复使用。'} />
            <div className="account-grid">
              <div className="panel profile-card"><div className="profile-avatar">{user?.display_name?.slice(0, 1) || 'U'}</div><h3>{user?.display_name}</h3><p>@{user?.username}</p><StatusPill tone={isAdmin ? 'warning' : 'neutral'}>{isAdmin ? '管理员' : '创作者'}</StatusPill></div>
              <form className="panel password-form" onSubmit={changePassword}>
                <label>当前密码<input type="password" autoComplete="current-password" value={passwordForm.current_password} onChange={(event) => setPasswordForm({ ...passwordForm, current_password: event.target.value })} /></label>
                <label>新密码<input type="password" autoComplete="new-password" value={passwordForm.new_password} onChange={(event) => setPasswordForm({ ...passwordForm, new_password: event.target.value })} /><span className="helper-text">至少 8 位，建议包含大小写字母、数字与符号。</span></label>
                <label>确认新密码<input type="password" autoComplete="new-password" value={passwordForm.confirm_password} onChange={(event) => setPasswordForm({ ...passwordForm, confirm_password: event.target.value })} /></label>
                <div className="form-actions"><button className="button primary" disabled={busy || !passwordForm.current_password || !passwordForm.new_password || !passwordForm.confirm_password}>更新密码</button></div>
              </form>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
