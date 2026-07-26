# 部署 Runbook

## 目标

- 本地工作根：`/mnt/demo/ainovel-ui`
- 云上目标：`/opt/xiaobai-one`
- 访问顺序：先 IP 访问，再绑定 `book.oiob.cn`
- 隔离原则：只使用 `xiaobai-*` 容器名、`/opt/xiaobai-one` 目录和独立端口，不触碰 `/opt/ainovel`

## 本地验证

```bash
cd /mnt/demo/ainovel-ui
./scripts/local-validate.sh
```

## 云上部署

```bash
sudo mkdir -p /opt/xiaobai-one
sudo rsync -av --delete \
  --exclude '.git/' \
  --exclude 'deploy/.env' \
  --exclude 'deploy/data/' \
  --exclude 'apps/api/.venv/' \
  --exclude 'apps/web/node_modules/' \
  --exclude 'apps/web/dist/' \
  /mnt/demo/ainovel-ui/ /opt/xiaobai-one/
cd /opt/xiaobai-one/deploy
# 首次部署才创建 .env；升级部署必须保留现有 deploy/.env 和 deploy/data。
test -f .env || cp .env.example .env
# 编辑 .env，至少更换 XIAOBAI_SECRET_KEY 和管理员密码。
# 生产真实生成必须明确设置 XIAOBAI_ENGINE_MODE=ainovel。
# 不要直接执行 docker compose up；deploy.sh 会把数据目录解析为宿主机绝对路径。
./deploy.sh
```

## 验收检查

```bash
curl -fsS http://127.0.0.1:3210/api/health | python3 -m json.tool
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep xiaobai
```
