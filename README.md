# 小白一号（ainovel-ui）

邀请制多用户的 AI 小说创作控制面。

> 当前状态：**MVP 第一刀已落地，可本地验证；下一步是 GitHub 推送、云上 `/opt/xiaobai-one` 部署与域名接入。**

## 本轮 plan review 结论

从第一性原理复核后，当前计划可执行，但有三个现实约束必须先接受：

1. **产品仓目前只有文档，没有代码**，所以第一步必须是脚手架与最小可运行闭环，而不是直接上云。
2. **不能影响现网服务**，所以必须坚持独立目录、独立容器名、独立网络、独立端口，不挂载 `/opt/ainovel`。
3. **没有现成操作者模型凭证可用于自动验收**，所以本地与首轮云上验收采用 `mock` 引擎完成闭环；系统同时保留 `ainovel-cli` 真引擎接线，待操作者保存凭证后切到 `ainovel` 模式即可。

## 已落地内容

- `apps/api`：FastAPI API
  - 引导管理员自动创建
  - 登录 / 邀请码 / 领取账号
  - 模型凭证保存（服务端加密）
  - 作品创建 / 列表 / 详情
  - 创作运行开始 / 暂停 / 继续
  - `mock` 引擎验收闭环
  - `ainovel-cli` Docker 运行适配层（按 env 切换）
- `apps/web`：React + Vite 控制面
  - 登录页 / 领取账号页
  - 邀请码管理
  - 模型凭证设置
  - 快速开始建书
  - 创作工作台
  - 只读产物浏览
- `deploy/`
  - 独立 compose
  - `.env.example`
  - `deploy.sh`
- `scripts/local-validate.sh`
  - 本地 Docker Compose 一键验证
- `docs/runbooks/deployment.md`
  - 本地 → 云上部署步骤

## 当前目录

```text
/mnt/demo/ainovel-ui
  apps/api
  apps/web
  deploy/
  scripts/
  docs/
  CONTEXT.md
  prd.md
  README.md
```

## 本地验证

```bash
cd /mnt/demo/ainovel-ui
./scripts/local-validate.sh
```

成功后访问：

```text
http://127.0.0.1:3210
```

默认引导管理员：

- 用户名：`admin`
- 密码：`ChangeMe123!`

> 本地 `mock` 模式下，启动创作后会自动生成大纲、进度和示例章节，用于验收页面与后台运行链路。

## 真引擎切换

部署时把 `deploy/.env` 中的：

```env
XIAOBAI_ENGINE_MODE=mock
```

改成：

```env
XIAOBAI_ENGINE_MODE=ainovel
```

随后操作者在网页中保存自己的模型凭证，系统会为每部作品生成独立 `ainovel-cli` 配置，并以独立容器运行。

## 隔离约束

- 容器名：`xiaobai-one-*`
- 网络：`xiaobai-one-net`
- 云上目录：`/opt/xiaobai-one`
- 本地暴露端口：`127.0.0.1:3210`
- 不读写 `/opt/ainovel`
- 不抢占现网 443；域名接入走现有反代新增独立规则

## 下一步

1. Git 初始化并推送到私有仓 `unixcs/ainovel-ui`
2. 云上同步到 `/opt/xiaobai-one`
3. IP 验收
4. 把 `book.oiob.cn` 反代到小白一号入口
