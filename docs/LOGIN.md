# 登录和记住账号密码

登录框默认勾选两个独立选项：

- **记住账号密码**：本地只记录账号名称和选项；密码交给浏览器密码管理器。支持 Credential Management API 的安全页面会请求浏览器保存，其他浏览器使用标准 `username` / `current-password` 自动填充。请按浏览器提示确认，是否保存与填充由浏览器设置决定。网站不会将密码写入 localStorage、sessionStorage 或 Cookie。
- **保持登录**：登录成功后由服务端设置 HttpOnly、SameSite=Lax 的持久 Cookie，默认 30 天。关闭标签页、浏览器或重启服务后，重新打开同一网站地址会通过 `/api/v1/me` 验证并恢复登录。取消勾选时只保留当前标签页 Token，不创建持久 Cookie。

已有旧版本登录需退出后重新登录一次，才能启用新的持久登录。`http://127.0.0.1:8080` 和 `http://localhost:8080` 属于不同站点存储，请固定使用同一地址。隐私模式、清除站点数据、浏览器禁止 Cookie 或凭证过期都会影响恢复。

“退出登录”会撤销服务端 Token 并清除持久 Cookie 和标签页凭证，不删除历史会话或浏览器已保存的密码。关闭“记住账号密码”后再次成功登录会清除网站记住的账号名称，不再主动请求保存密码；浏览器里已保存的密码需在浏览器密码管理器中管理。

服务连接失败时会提示“退出登录未完成”，保留当前状态，以便重试撤销。重新登录成功会撤销该浏览器之前的持久凭证，防止取消保持登录后恢复到旧账号。

## 配置和接口

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `TOKEN_TTL_SECONDS` | 86400 | 普通标签页/API Token 有效期 |
| `REMEMBER_TOKEN_TTL_SECONDS` | 2592000 | 保持登录有效期，30 天；最大 90 天 |
| `AUTH_COOKIE_SECURE` | false | 本地 HTTP 开发使用 false；HTTPS 部署设置 true |

Cookie 仅发送给当前主机的 `/api/v1` 路径，前端脚本不能读取 Cookie 内容。服务端数据库仍只保存 Token 摘要，Cookie 到期和数据库到期保持一致，不使用长期明文密码自动重新登录。没有自动无限续期。

`POST /api/v1/auth/login` 在用户名和密码之外接受 `remember_me: true`。省略该字段保持原 API 行为：返回普通 Bearer Token，不创建持久 Cookie。所有既有 Bearer API 调用继续有效。

浏览器 API 请求使用 `credentials: same-origin`。使用 Cookie 认证的写入请求还必须携带 `X-GoMate-Request: web`；跨站请求被拒绝，不开启任意来源 CORS。API 客户端仍可用 Authorization Bearer。

凭证保存遵循 [MDN PasswordCredential 文档](https://developer.mozilla.org/en-US/docs/Web/API/PasswordCredential/PasswordCredential) 和 [CredentialsContainer.store 文档](https://developer.mozilla.org/en-US/docs/Web/API/CredentialsContainer/store)；持久 Cookie 行为见 [MDN Set-Cookie 文档](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie)。

## 验证

`python scripts/smoke_browser_session.py` 经本地前端代理验证 Cookie 属性、新客户端恢复、写入保护和退出撤销。只使用随机测试账号，不调用模型、地图或外部服务。
