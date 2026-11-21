# 前后端 Docker 启动

## 一键启动

要求 Docker Desktop 已启动，并使用 Linux containers。

```powershell
cd D:\test\gomate_agent
docker compose up -d --build --wait
```

- 页面：http://127.0.0.1:8080
- 接口文档：http://127.0.0.1:8080/docs
- 健康检查：http://127.0.0.1:8080/health/ready

没有 `.env` 或 API Key 也能启动当前基础功能。需要配置时，将 `.env.example` 复制为 `.env` 后在本机填写；不要覆盖已有密钥文件。
根目录 `.env` 中的 `GOMATE_WEB_PORT` 可修改宿主机端口，默认 8080。

## 服务与数据

| 服务 | 镜像构建 | 容器端口 | 作用 |
| --- | --- | --- | --- |
| frontend | Node 24 构建，Nginx 非 root 静态服务 | 8080 | 页面、固定后端代理 |
| backend | Python 3.13 多阶段构建、非 root 运行 | 8000 | FastAPI、SQLite、单 worker |

浏览器只访问前端地址，`/api/` 和 `/health/` 由 Nginx 转发。后端没有映射到宿主机端口；开发中原有的本机 8000 服务可独立存在。
前端等待后端健康检查通过再启动。两个容器使用只读根文件系统，临时文件写入 tmpfs。

SQLite 保存在 Compose 命名卷 `gomate_data` 对应的 `/app/data/gomate.db` 中。
这与本机直接运行时的 `data/gomate.db` 是两个独立数据库，首次在容器中使用需要重新注册账号。
本机旧数据不自动导入，避免启动时覆盖已有账号和会话。

```powershell
docker compose ps
docker compose logs -f --tail=100
docker compose stop
docker compose start
docker compose down
```

`stop`、`down` 保留命名卷。不要为日常停止服务添加 `-v`，该选项会删除容器数据库。
备份应使用 SQLite backup API 或停服后导出完整一致的数据，不能在运行中只复制主文件而忽略 WAL。

## 配置与构建

- 后端的运行依赖锁在 `requirements.runtime.lock`，开发测试依赖仍在 `requirements.lock`。
- 前端的依赖锁在 `frontend/package-lock.json`，镜像使用 `npm ci`。
- 根目录和前端目录分别提供 `.dockerignore`；源码凭证、Git 元数据、本机数据库、虚拟环境和 node_modules 不进入构建上下文。
- DeepSeek、高德 Web 服务 Key 只由 Compose 在运行时传入 backend，前端镜像不包含这些密钥。
- `.env` 的环境变量可通过本机进程环境覆盖；不要把 `docker compose config` 展开的敏感值粘贴到日志或提交中，检查时使用 `docker compose config --quiet`。
- 当前默认仅绑定宿主机 `127.0.0.1`，用于本地使用。公网部署需另行配置域名、HTTPS 和入口限流。

## 验证

```powershell
docker compose config --quiet
docker compose up -d --build --wait
python scripts/smoke_docker.py
```

冒烟脚本使用随机测试账号与会话，经前端代理验证注册、登录、消息、幂等、实际 Run 状态和登出。它只输出检查结果，不输出密码或 Token。

额外验证容器重启后的数据持久化：

```powershell
python scripts/smoke_docker.py --check-restart
```

该选项会重启当前 Compose 项目的 backend，需在没有其他活跃任务时运行。测试后删除本次创建的会话并撤销登录 Token，随机测试账号会保留为空账号。

完整行程生成、真实高德查询和多 Agent 编排尚未接入；Docker 封装不会自动启用这些能力。
