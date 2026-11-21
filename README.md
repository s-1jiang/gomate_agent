# 逛搭 GoMate

面向本地生活的规划 Agent。需求基线见 [项目框架](GOMATE_PROJECT_FRAMEWORK.md)，当前提供 **React 前端 + FastAPI/SQLite 基础框架 + Docker Compose 本地封装**。

已确定模型供应商为 **DeepSeek API**；国内地图方案建议采用 **高德 Web 服务 + JS API 2.0**。地图接入设计见 [供应商方案](docs/PROVIDERS.md)。

## Docker 一键打开

Docker Desktop 使用 Linux containers，启动后执行：

```powershell
cd D:\test\gomate_agent
docker compose up -d --build --wait
```

打开 **http://127.0.0.1:8080**。接口调试页面为 http://127.0.0.1:8080/docs。
初次使用在页面注册账号即可，当前基础功能不要求配置外部 API Key。

前后端独立镜像，通过 Nginx 同源转发 API，SQLite 使用命名卷持久化。容器数据库与本机旧数据库独立；详情和停止/重启方式见 [Docker 说明](docs/DOCKER.md)。

## 不使用 Docker 开发（Windows / PowerShell）

要求 Python 3.11+；本次在 Windows + Python 3.13 验证。

```powershell
cd D:\test\gomate_agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m app.db.database
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000/docs。启动时也会检查并应用未执行的版本化迁移。

另开一个终端启动前端：

```powershell
cd D:\test\gomate_agent\frontend
npm.cmd ci
npm.cmd run dev
```

打开 http://127.0.0.1:5173。前端开发代理默认转发到本机 8000，无需额外配置跨域。

当前运行器是进程内开发骨架，**仅支持单个 Uvicorn worker**。启动会把上个进程遗留的 queued/running 任务标记为 interrupted；不要用多个进程共享此运行器。

## 已有能力

- `/health/live`、`/health/ready`、OpenAPI 文档与请求 ID。
- SQLite 版本化迁移、外键、WAL、短事务。
- 注册、登录、Token 摘要存储、到期验证、注销与持久化登录限速。
- 用户隔离的会话、消息历史、分页与级联删除。
- 消息幂等、Run 查询/取消、会话租约、递增 fencing token 与重启中断处理。
- DeepSeek 文本调用适配器、内存共享预算、计划基础约束及 Agent/检索扩展契约。
- 不依赖外部密钥的单元、API、隔离和供应商协议测试。
- React 页面：注册登录、城市选择、会话搜索/切换/删除确认、消息草稿、运行状态及取消；适配手机与桌面。
- 前后端 Dockerfile、Nginx 同源代理、健康检查、只读容器和持久化数据卷。

**尚未接入业务链路**：DeepSeek 工具调用、多 Agent 工作流、私有向量检索与重排、偏好抽取、MCP 协议服务、高德真实地图和报告。页面中的行程区明确显示准备中，当前聊天仅保存需求。目录或接口契约存在不代表功能已实现。完整状态见 [实施状态](docs/IMPLEMENTATION_STATUS.md)。

## 试用基础接口

在 `/docs` 中按顺序操作：

1. `POST /api/v1/auth/register`：用户名 3–64 位（字母、数字、`_.-`），密码 12–128 位。
2. `POST /api/v1/auth/login`：使用相同 JSON 凭据，取得 `access_token`；点击 Authorize 填入 Token。
3. `POST /api/v1/conversations`：提交 `{"title":"周末安排"}`。
4. `POST /api/v1/conversations/{id}/messages`：提交 `{"client_message_id":"demo-001","content":"帮我规划半日游"}`。
5. 返回 202 和 Run；通过 `GET /api/v1/runs/{id}` 查看状态。

当前消息会被真实保存，基础运行器随后明确返回 `failed / WORKFLOW_NOT_IMPLEMENTED`，不会伪造出游计划或产生供应商费用。同一消息 ID 重放返回同一个 Run；换内容重用 ID 返回 409。

登录接口每个账户与来源地址默认 5 次 / 300 秒（成功和失败均计数），地址总量另有上限。默认仅绑定本机地址，面向公网部署前应增加 HTTPS、注册限流及网关策略。

## 配置

复制 `.env.example` 后在本机填写。不要提交 `.env`、私有数据库、真实文件或密钥。

```dotenv
DEEPSEEK_API_KEY=在本机填写
DEEPSEEK_MODEL=deepseek-flash
AMAP_WEB_SERVICE_KEY=后端Web服务Key
AMAP_JS_API_KEY=单独申请的浏览器JSKey
AMAP_JS_SECURITY_CODE=仅保存在服务端的JS安全密钥
DEFAULT_CITY=首个服务城市
```

模型名可配置，应根据 DeepSeek 控制台可用型号选择；填写密钥不会自动启用尚未完成的规划工作流。当前检索 Embedding / Rerank 供应商仍待确定，不能把聊天模型接口当作向量接口。

## 目录

```text
app/
  api/ schemas/ core/       HTTP、数据契约、认证和配置
  db/migrations/           SQLite 迁移和带身份的 Repository
  services/                应用服务
  agents/ workflows/       角色注册与工作流状态契约
  memory/ retrieval/       画像和私有检索的扩展入口
  planning/ tools/         基础约束、预算与可信上下文
  integrations/            DeepSeek 适配器、地图供应商契约
  mcp_servers/ jobs/ web/   后续协议、后台任务及页面入口
  observability/           脱敏请求日志
tests/                     unit、integration、isolation、mcp
frontend/                  React / TypeScript / Vite 页面与测试
scripts/                   Docker 联调与持久化冒烟
eval/                      后续场景评测的目录约定
docs/                      供应商设计与当前实施状态
data/                      本地运行数据，不进入 Git
```

## 检查

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m ruff format --check app tests
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
cd frontend
npm.cmd test
npm.cmd run build
```

`requirements.lock` 记录基础和开发依赖，`requirements.runtime.lock` 用于后端容器。前端依赖由 package-lock.json 锁定。CI 覆盖后端、前端和 Compose 配置检查，不调用真实 DeepSeek 或地图服务。
