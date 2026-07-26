# 小白一号（ainovel-ui）

邀请制、多用户的 AI 小说创作控制面，支持真实 `ainovel-cli` 引擎与隔离的本地 `mock` 验收模式。

## 当前状态（2026-07-26）

- 生产站点：`https://book.oiob.cn`
- 生产引擎：`ainovel`
- 云端目录：`/opt/xiaobai-one`
- 独立容器：`xiaobai-one-api`、`xiaobai-one-web`
- 独立网络：`xiaobai-one-net`
- API、真实模型生成、章节实时预览、单章下载、全书导出、桌面与移动端 UI 均已完成验收

> `mock` 仅用于本地工作流验证。生产环境必须显式设置 `XIAOBAI_ENGINE_MODE=ainovel`，页面也会明确显示当前运行类型，避免把模拟短文误认为正式小说。

## 核心能力

### API

- 引导管理员、登录、首次改密、邀请码领取与作废
- 用户级模型凭证加密存储，只有“已保存且同参数真实测试成功”的配置才能启动真实生成
- 作品创建、状态查询、开始、暂停、继续
- 每用户与全站并发上限
- API 重启后恢复真实任务监控；Docker 不可用、容器丢失或停止失败时 fail closed
- 根据实际章节文件扫描进度，达到目标章节后主动停止引擎
- 章节全文、字符数、段落数、更新时间、单章 TXT 和全书 TXT 导出

### Web

- Claude/Anthropic 式暖白纸张、暖灰导航与陶土主色，阅读内容优先
- 桌面侧栏与移动端底部导航
- 真实/模拟引擎醒目标识
- 运行期间每 2.5 秒刷新作品和当前章节全文
- 默认跟随最新章节；用户主动选择旧章节后不强制跳转
- 章节复制、下载、全书导出
- 401 自动退出、首次改密保护、表单与无障碍标签完善

## 目录

```text
apps/api/                 FastAPI API、引擎适配与测试
apps/web/                 React + Vite Web UI
deploy/                   独立 Docker Compose 与部署脚本
docs/                     ADR、实现审查和部署手册
scripts/local-validate.sh  隔离的本地 Compose 烟测
```

## 本地开发验证

API：

```bash
cd apps/api
. .venv/bin/activate
pytest -q
```

Web：

```bash
cd apps/web
npm ci
npm run build
```

隔离 Compose 烟测：

```bash
cd /mnt/demo/ainovel-ui
./scripts/local-validate.sh
```

默认访问 `http://127.0.0.1:33210`。该脚本使用独立的项目名、端口、网络和 `tmp/local-validate-data`，不会覆盖 `deploy/.env`、`deploy/data` 或正在运行的生产/开发栈。可通过 `XIAOBAI_VALIDATE_PORT` 等环境变量改写。

## 真引擎部署要点

生产 `.env` 至少需要：

```env
XIAOBAI_ENGINE_MODE=ainovel
XIAOBAI_HOST_DATA_DIR=/absolute/host/path/to/deploy/data
XIAOBAI_AINOVEL_MEMORY=768m
XIAOBAI_AINOVEL_CPUS=1.0
XIAOBAI_AINOVEL_PIDS_LIMIT=256
XIAOBAI_ACTIVE_RUNS_PER_OPERATOR=1
XIAOBAI_ACTIVE_RUNS_GLOBAL=1
```

`XIAOBAI_HOST_DATA_DIR` 必须是宿主机绝对路径，因为 API 通过 Docker socket 创建子容器并挂载作品目录。真实模式缺失或使用相对路径时，API 会拒绝启动，而不是静默挂载错误目录。

部署必须使用 `deploy/deploy.sh`；升级同步必须排除生产 `deploy/.env` 与 `deploy/data/`。完整步骤见 `docs/runbooks/deployment.md`。

## 安全与运行边界

- 不读写 `/opt/ainovel`
- 不抢占现网 443；域名由既有反代转发到独立 Web 端口
- 每个生成子容器限制内存、CPU 和 PID 数
- `config.json` 权限为 `0600`，配置目录为 `0700`
- API Key 不在前端回显，不得写入 Git；若曾进入 Git 历史，必须轮换并另行清理历史
- 当前 API 仍挂载 `/var/run/docker.sock`；长期应改为受限 socket proxy 或专用任务执行器
