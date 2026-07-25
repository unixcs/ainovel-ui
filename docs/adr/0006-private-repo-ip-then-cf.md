# 私有产品仓 + 先 IP 后 Cloudflare 域名

小白一号以单一私有 GitHub 产品仓交付，不公开自托管模板，也不拆成核心仓/部署仓双层。仓库根目录固定为本地 `/mnt/demo/ainovel-ui`（Windows 侧对应 `\mnt\demo\ainovel-ui`），内含 Web、控制面、Compose 与文档；运行时依赖官方 `ainovel-cli` 镜像，不把现网 `/opt/ainovel` 数据或番茄发布系统打进本仓。访问顺序是：云上先用服务器 IP + 独立端口或独立反代入口验证，再按需绑定 Cloudflare 域名；CF Token 仅在绑定时提供，不进入 Git。与现网隔离的云上目标目录使用独立路径（如 `/opt/xiaobai-one`），禁止挂载现网 CLI 版作品目录。
