import { useState, type FormEvent } from "react";
import { Compass, Eye, EyeOff, LoaderCircle } from "lucide-react";
import { ApiClient, errorMessage, type User } from "../api";
import { Dialog } from "./Dialog";
import { loginPreferences, rememberedUsername, saveLoginPreferences } from "../loginPreferences";

export function AuthDialog({
  onClose,
  onAuthenticated,
}: {
  onClose: () => void;
  onAuthenticated: (token: string, user: User, keepSignedIn: boolean) => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [registered, setRegistered] = useState(false);
  const [preferences] = useState(loginPreferences);
  const [rememberCredentials, setRememberCredentials] = useState(preferences.rememberCredentials);
  const [keepSignedIn, setKeepSignedIn] = useState(preferences.keepSignedIn);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const credentials = {
      username: String(data.get("username")),
      password: String(data.get("password")),
    };
    setBusy(true);
    setError("");
    try {
      const api = new ApiClient();
      if (mode === "register" && !registered) {
        await api.register(credentials);
        setRegistered(true);
      }
      const result = await api.login(credentials, keepSignedIn);
      const user = await new ApiClient(result.access_token).me();
      saveLoginPreferences(credentials, rememberCredentials, keepSignedIn);
      onAuthenticated(result.access_token, user, keepSignedIn);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={mode === "login" ? "登录逛搭" : "注册账号"}
      onClose={onClose}
      busy={busy}
      className="auth-dialog"
    >
      <div className="auth-brand">
        <Compass size={24} />
      </div>
      <p className="muted auth-subtitle">
        登录后可保存出行需求，并查看历史会话。
      </p>
      <div className="auth-tabs" role="tablist" aria-label="账户操作">
        {(["login", "register"] as const).map((value) => (
          <button
            key={value}
            role="tab"
            aria-selected={mode === value}
            disabled={busy}
            onClick={() => {
              setMode(value);
              setError("");
              setRegistered(false);
            }}
          >
            {value === "login" ? "登录" : "注册账号"}
          </button>
        ))}
      </div>
      <form onSubmit={submit} className="auth-form">
        <label>
          用户名
          <input
            key={mode}
            defaultValue={mode === "login" ? rememberedUsername() : ""}
            name="username"
            autoComplete="username"
            required
            minLength={3}
            maxLength={64}
            pattern="[a-zA-Z0-9_.\-]+"
            placeholder="3 位以上字母、数字或 _ . -"
            disabled={busy}
            autoFocus
          />
        </label>
        <label>
          密码
          <span className="password-field">
            <input
              name="password"
              type={visible ? "text" : "password"}
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
              required
              minLength={12}
              maxLength={128}
              placeholder="至少 12 位"
              disabled={busy}
            />
            <button
              type="button"
              className="icon-button"
              aria-label={visible ? "隐藏密码" : "显示密码"}
              onClick={() => setVisible(!visible)}
            >
              {visible ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </span>
        </label>
        <div className="auth-options">
          <label>
            <input type="checkbox" checked={rememberCredentials} disabled={busy}
              onChange={(event) => setRememberCredentials(event.target.checked)} />
            记住账号密码
          </label>
          <label>
            <input type="checkbox" checked={keepSignedIn} disabled={busy}
              onChange={(event) => setKeepSignedIn(event.target.checked)} />
            保持登录
          </label>
        </div>
        <p className="auth-remember-note">
          密码由浏览器密码管理器保存和填充，请按浏览器提示确认。保持登录默认有效期为 30 天。
        </p>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        {registered && error && (
          <p className="muted small">
            账号已创建，可以用刚才的用户名和密码登录。
          </p>
        )}
        <button
          className="button primary auth-submit"
          disabled={busy}
          type="submit"
        >
          {busy && <LoaderCircle size={18} className="spin" />}
          {busy
            ? "请稍候…"
            : mode === "login" || registered
              ? "登录逛搭"
              : "创建账号并登录"}
        </button>
      </form>
      <p className="auth-footnote">
        会话仅本人可见。退出登录不会删除历史消息。
      </p>
    </Dialog>
  );
}
