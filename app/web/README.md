# Web 页面

React + TypeScript + Vite 前端位于仓库根目录 `frontend/`。

本地开发通过 Vite 将 `/api` 和 `/health` 转发给 FastAPI；Docker 中由 Nginx 完成同源转发。
生产静态文件独立封装在前端镜像中，FastAPI 保留 API 与 `/docs` 调试页面。

当前接通注册、登录、会话、消息保存和 Run 状态；行程地图为明确的待生成功能，尚未调用高德。
地图接入仍遵循 `docs/PROVIDERS.md` 的 Plan JSON 和坐标系约定。
