# GoMate Web

React + TypeScript + Vite。所有请求走同源 `/api/v1`，开发代理在 `vite.config.ts`，容器代理在 `nginx.conf`。

```powershell
npm.cmd ci
npm.cmd run dev
```

默认 http://127.0.0.1:5173，后端默认 http://127.0.0.1:8000。需要改后端地址时设置仅开发服务器使用的 `GOMATE_API_TARGET`。

```powershell
npm.cmd test
npm.cmd run build
```

- 页面支持注册登录、城市选择、草稿、历史会话、搜索、删除确认、保存消息、Run 轮询与取消。
- Token 只保存在当前标签页的 sessionStorage，退出/失效时清空页面中的用户数据；不存储密码。
- API 失败保留草稿，重试同一条消息复用幂等键。
- 快速切换会话时放弃旧请求，避免晚到的历史覆盖当前页面。
- 文字聊天在 Run 终态后自动读取真实回复；失败显示服务端错误，不伪造模型回答。
- “知识库”支持文本导入和可见范围选择；回复下展示服务端检索来源、行号和原文，区分已引用与只召回。
- 当前检索为本地关键词匹配，向量召回/重排、真实地图和完整行程尚未接入。
- 不在前端环境变量中放 DeepSeek 或高德 Web 服务密钥。静态构建不需要任何外部凭证。

容器启动方式见 `../docs/DOCKER.md`。
