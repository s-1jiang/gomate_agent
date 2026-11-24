# 逛搭 GoMate

面向本地生活的规划 Agent。需求基线见 [项目框架](GOMATE_PROJECT_FRAMEWORK.md)，当前提供 **Supervisor 多 Agent 地点搜索、文字聊天、私有文本知识库与来源标签、React 前端和 Docker Compose 本地封装**。

已确定模型供应商为 **DeepSeek API**；国内地图方案建议采用 **高德 Web 服务 + JS API 2.0**。地图接入设计见 [供应商方案](docs/PROVIDERS.md)。

## Docker 一键打开

Docker Desktop 使用 Linux containers，启动后执行：
首次部署先从 `.env.example` 创建 `.env` 并设置随机 `RABBITMQ_PASSWORD`；已有本机配置已补齐。

```powershell
cd D:\test\gomate_agent
docker compose up -d --build --wait
```

打开 **http://127.0.0.1:8080**。接口调试页面为 http://127.0.0.1:8080/docs。
初次使用在页面注册账号。在 `.env` 中配置有效的 `DEEPSEEK_API_KEY` 后可进行文字聊天；注册、会话管理和资料检索不需要模型密钥。模型调用按供应商规则计费。

登录时默认勾选“记住账号密码”和“保持登录”。密码由浏览器密码管理器保存，保持登录默认 30 天，关闭后重新打开同一地址可恢复；主动退出或凭证过期后需重新登录。已有旧版本登录需退出后重新登录一次。说明见 [登录与账号记忆](docs/LOGIN.md)。

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

Docker 通过 RabbitMQ 和独立 Worker 执行任务，API 重启与网页会话切换不会取消生成。消息和任务使用事务 Outbox，完成结果保存到 SQLite，再由前端恢复。原生开发默认 inline 单进程调试；两种模式的配置和重启行为见 [后台队列](docs/RUN_QUEUE.md)。

## 已有能力

- `/health/live`、`/health/ready`、OpenAPI 文档与请求 ID。
- SQLite 版本化迁移、外键、WAL、短事务。
- 注册、登录、Token 摘要存储、到期验证、注销与持久化登录限速。
- 用户隔离的会话、消息历史、分页与级联删除。
- 消息幂等、Run 查询/取消、会话租约、递增 fencing token 与重启中断处理。
- DeepSeek 多轮文字聊天、取消/超时、回复保存与模型错误提示；预算计数写入 Run。
- Supervisor 分派地点/餐饮/游玩任务，审查结果并按任务版本定向退回；达到上限后不发布未经审查的地点。
- 高德城市关键词搜索、真实 POI/GCJ-02 坐标来源、地点列表与按需加载的地图标记。
- TXT/Markdown 文本资料入库，用户/会话范围隔离，关键词检索与可展开的来源标签。
- 不依赖外部密钥的单元、API、隔离和供应商协议测试。
- React 页面：注册登录、城市选择、会话搜索/切换/删除确认、消息草稿、运行状态及取消；适配手机与桌面。
- 前后端 Dockerfile、Nginx 同源代理、健康检查、只读容器和持久化数据卷。

**尚未接入业务链路**：原生模型工具调用协议、向量检索与重排、偏好抽取、MCP 协议服务、天气与独立报告。多 Agent 同城行程已使用 Python 异步状态机，支持高德交通查询、时间安排和可选 Tavily 网页来源；不依赖 LangGraph。知识检索仍使用本地关键词匹配。完整状态见 [实施状态](docs/IMPLEMENTATION_STATUS.md)。

游玩需求会输出完整时间轴、每站停留与玩法、逐段交通和返程，并在回答中嵌入地图。时间冲突和不合适的方案会退回行程 Agent 修改。示例与 Tavily 配置见 [行程说明](docs/ITINERARY.md)。

在右侧“地点搜索”输入城市和关键词，或直接在对话中提出地点需求。Supervisor 会决定分派、追问或答复，只有审查通过的供应商 POI 会进入地图。页面展示地点和来源，任务分发与审查记录保留在后端。配置与范围见 [地图搜索说明](docs/MAP_SEARCH.md)。

## 试用基础接口

在 `/docs` 中按顺序操作：

1. `POST /api/v1/auth/register`：用户名 3–64 位（字母、数字、`_.-`），密码 12–128 位。
2. `POST /api/v1/auth/login`：使用相同 JSON 凭据，取得 `access_token`；点击 Authorize 填入 Token。
3. `POST /api/v1/conversations`：提交 `{"title":"周末安排"}`。
4. `POST /api/v1/conversations/{id}/messages`：提交 `{"client_message_id":"demo-001","content":"帮我规划半日游"}`。
5. 返回 202 和 Run；通过 `GET /api/v1/runs/{id}` 查看状态。

当前运行器调用 DeepSeek，并将真实回复和检索证据保存到当前会话。缺少密钥、余额不足或鉴权失败时会返回明确错误。同一消息 ID 重放返回同一个 Run，不重复调用模型；换内容重用 ID 返回 409。

在页面右上角打开“知识库”，添加资料后提问即可查看来源。无检索命中时仍可正常聊天，不额外展示检索过程说明。来源标签示例、权限与接口见 [文字聊天和来源说明](docs/CHAT_AND_RAG.md)。

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

模型名可配置，应根据 DeepSeek 控制台可用型号选择。可选 `TAVILY_API_KEY` 用于游玩资料检索，缺少时玩法为未核实建议。当前检索 Embedding / Rerank 供应商仍待确定，不能把聊天模型接口当作向量接口。

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
  jobs/                    RabbitMQ、事务 Outbox 与任务归属/心跳
  worker.py                独立任务消费者入口
  mcp_servers/ web/        后续协议及页面入口
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
