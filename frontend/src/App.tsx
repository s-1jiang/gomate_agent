import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  Compass,
  Info,
  LoaderCircle,
  LogOut,
  MapPin,
  Menu,
  MessageCircle,
  PanelRightOpen,
  Plus,
  Search,
  Square,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import {
  ApiClient,
  ApiError,
  errorMessage,
  isActiveRun,
  type Conversation,
  type Message,
  type Run,
  type User,
} from "./api";
import { AuthDialog } from "./components/AuthDialog";
import { Dialog } from "./components/Dialog";
import { KnowledgeDialog } from "./components/KnowledgeDialog";
import { MessageSources } from "./components/MessageSources";
import { PlanPanel } from "./components/PlanPanel";
import { Welcome } from "./components/Welcome";

const TOKEN_KEY = "gomate.session";
function storedToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
function saveToken(value: string | null) {
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* memory-only session still works */
  }
}
function timeLabel(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

export default function App() {
  const [token, setToken] = useState(storedToken);
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(!!token);
  const [authOpen, setAuthOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [listing, setListing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [currentRun, setCurrentRun] = useState<Run | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [city, setCity] = useState("");
  const [cityOpen, setCityOpen] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [cityDraft, setCityDraft] = useState("");
  const [deleting, setDeleting] = useState<Conversation | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [service, setService] = useState<"checking" | "online" | "offline">(
    "checking",
  );
  const api = useMemo(() => new ApiClient(token), [token]);
  const composer = useRef<HTMLTextAreaElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const epoch = useRef(0);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const pending = useRef<{
    sessionId: string;
    content: string;
    clientId: string;
  } | null>(null);
  const draftKey = selected || "new";
  const draft = drafts[draftKey] || "";

  const clearSession = useCallback(() => {
    setKnowledgeOpen(false);
    epoch.current += 1;
    saveToken(null);
    setToken(null);
    setUser(null);
    setConversations([]);
    setSelected(null);
    setMessages([]);
    setDrafts({});
    setCurrentRun(null);
    setHasMore(false);
    setCity("");
    setQuery("");
    setSending(false);
    setHistoryLoading(false);
    setListing(false);
    setChecking(false);
    setSidebarOpen(false);
    setPlanOpen(false);
    pending.current = null;
  }, []);
  const handleError = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        clearSession();
        setNotice("登录已过期，请重新登录后继续。");
        setAuthOpen(true);
      } else setNotice(errorMessage(error));
    },
    [clearSession],
  );

  useEffect(() => {
    const controller = new AbortController();
    fetch("/health/ready", { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted)
          setService(response.ok ? "online" : "offline");
      })
      .catch(() => {
        if (!controller.signal.aborted) setService("offline");
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!token) {
      setChecking(false);
      return;
    }
    const controller = new AbortController();
    setChecking(true);
    api
      .me(controller.signal)
      .then((nextUser) => {
        if (!controller.signal.aborted) setUser(nextUser);
      })
      .catch((error) => {
        if (!controller.signal.aborted) handleError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecking(false);
      });
    return () => controller.abort();
  }, [api, token, handleError]);

  useEffect(() => {
    if (!user) return;
    const controller = new AbortController();
    setListing(true);
    api
      .conversations(0, controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return;
        setConversations((current) => {
          const merged = new Map(
            [...items, ...current].map((item) => [item.id, item]),
          );
          return [...merged.values()].sort((a, b) =>
            b.created_at.localeCompare(a.created_at),
          );
        });
        setHasMore(items.length === 100);
      })
      .catch((error) => {
        if (!controller.signal.aborted) handleError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setListing(false);
      });
    return () => controller.abort();
  }, [api, user?.id, handleError]);

  useEffect(() => {
    setMessages([]);
    if (!selected || !user) {
      setHistoryLoading(false);
      return;
    }
    const controller = new AbortController();
    setHistoryLoading(true);
    async function readHistory() {
      const all: Message[] = [];
      let cursor: string | undefined;
      while (!controller.signal.aborted) {
        const page = await api.messages(selected!, cursor, controller.signal);
        all.push(...page);
        if (page.length < 100) break;
        cursor = page[page.length - 1].id;
      }
      if (!controller.signal.aborted)
        setMessages((current) => {
          const merged = new Map(
            [...current, ...all].map((item) => [item.id, item]),
          );
          return [...merged.values()].sort(
            (a, b) =>
              a.created_at.localeCompare(b.created_at) ||
              a.id.localeCompare(b.id),
          );
        });
    }
    readHistory()
      .catch((error) => {
        if (!controller.signal.aborted) handleError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setHistoryLoading(false);
      });
    return () => controller.abort();
  }, [api, selected, user?.id, handleError, historyVersion]);

  useEffect(() => {
    if (!currentRun || isActiveRun(currentRun) || currentRun.session_id !== selected) return;
    const controller = new AbortController();
    const run = currentRun;
    api.messages(run.session_id, run.message_id, controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setMessages((previous) => {
        const merged = new Map([...previous, ...items].map((item) => [item.id, item]));
        return [...merged.values()].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
      });
    }).catch((error) => { if (!controller.signal.aborted) handleError(error); });
    return () => controller.abort();
  }, [api, currentRun?.id, currentRun?.status, selected, handleError]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, currentRun?.status]);
  useEffect(() => {
    const node = composer.current;
    if (node) {
      node.style.height = "auto";
      node.style.height = `${Math.min(node.scrollHeight, 170)}px`;
    }
  }, [draft]);

  useEffect(() => {
    if (!currentRun || !isActiveRun(currentRun)) return;
    const controller = new AbortController();
    const runId = currentRun.id;
    let timer: ReturnType<typeof setTimeout>;
    const started = Date.now();
    async function poll() {
      try {
        const run = await api.run(runId, controller.signal);
        if (controller.signal.aborted) return;
        setCurrentRun(run);
        if (isActiveRun(run) && Date.now() - started < 130000)
          timer = setTimeout(poll, 1000);
        else if (isActiveRun(run))
          setNotice("任务仍在处理中，可以稍后重新打开会话查看。");
      } catch (error) {
        if (!controller.signal.aborted) handleError(error);
      }
    }
    timer = setTimeout(poll, 250);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [api, currentRun?.id, currentRun?.status, handleError]);

  function selectConversation(id: string | null) {
    selectedRef.current = id;
    setSelected(id);
    setSidebarOpen(false);
    setNotice("");
    setCurrentRun(null);
    if (id === null) {
      setMessages([]);
      setCurrentRun(null);
    }
  }
  function suggest(value: string) {
    setDrafts((previous) => ({ ...previous, [draftKey]: value }));
    composer.current?.focus();
  }
  function authenticate(nextToken: string, nextUser: User) {
    epoch.current += 1;
    saveToken(nextToken);
    setToken(nextToken);
    setUser(nextUser);
    setAuthOpen(false);
    setNotice("");
  }
  async function logout() {
    try {
      await api.logout();
    } catch {
      setNotice("已退出当前页面，服务连接暂时不可用。");
    } finally {
      clearSession();
    }
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    if (!draft.trim() || sending || isActiveRun(currentRun) || historyLoading)
      return;
    if (!user) {
      setAuthOpen(true);
      return;
    }
    const version = epoch.current;
    const originalKey = draftKey;
    const originalSelected = selected;
    const content = city ? `城市：${city}\n${draft.trim()}` : draft.trim();
    setSending(true);
    setNotice("");
    let sessionId = selected;
    try {
      if (!sessionId) {
        const conversation = await api.createConversation(
          Array.from(draft.trim()).slice(0, 24).join(""),
        );
        if (version !== epoch.current) return;
        sessionId = conversation.id;
        setConversations((items) => [conversation, ...items]);
        if (selectedRef.current !== originalSelected) return;
        selectedRef.current = sessionId;
        setSelected(sessionId);
        setDrafts((items) => ({ ...items, [sessionId!]: draft }));
      }
      if (
        !pending.current ||
        pending.current.sessionId !== sessionId ||
        pending.current.content !== content
      ) {
        pending.current = { sessionId, content, clientId: crypto.randomUUID() };
      }
      const run = await api.sendMessage(
        sessionId,
        content,
        pending.current.clientId,
      );
      if (version !== epoch.current) return;
      pending.current = null;
      setDrafts((items) => ({ ...items, [originalKey]: "", [sessionId!]: "" }));
      const ownMessage: Message = {
        id: run.message_id,
        role: "user",
        content,
        client_message_id: null,
        created_at: run.created_at,
      };
      if (selectedRef.current === sessionId) {
        setMessages((items) =>
          items.some((item) => item.id === ownMessage.id)
            ? items
            : [...items, ownMessage],
        );
        setCurrentRun(run);
      }
    } catch (error) {
      if (version === epoch.current) handleError(error);
    } finally {
      if (version === epoch.current) setSending(false);
    }
  }

  function composerKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void send();
    }
  }
  async function cancelRun() {
    if (!currentRun) return;
    const version = epoch.current;
    setCancelling(true);
    try {
      const run = await api.cancelRun(currentRun.id);
      if (version === epoch.current && selectedRef.current === run.session_id)
        setCurrentRun(run);
    } catch (error) {
      if (version === epoch.current) handleError(error);
    } finally {
      setCancelling(false);
    }
  }
  async function deleteConversation() {
    if (!deleting) return;
    const version = epoch.current;
    setDeleteBusy(true);
    try {
      await api.deleteConversation(deleting.id);
      if (version !== epoch.current) return;
      setConversations((items) =>
        items.filter((item) => item.id !== deleting.id),
      );
      if (selected === deleting.id) selectConversation(null);
      setDrafts((items) => {
        const next = { ...items };
        delete next[deleting.id];
        return next;
      });
      setDeleting(null);
    } catch (error) {
      if (version === epoch.current) handleError(error);
    } finally {
      setDeleteBusy(false);
    }
  }
  async function moreConversations() {
    const version = epoch.current;
    setListing(true);
    try {
      const items = await api.conversations(conversations.length);
      if (version === epoch.current) {
        setConversations((previous) => [...previous, ...items]);
        setHasMore(items.length === 100);
      }
    } catch (error) {
      if (version === epoch.current) handleError(error);
    } finally {
      if (version === epoch.current) setListing(false);
    }
  }

  const filtered = conversations.filter((item) =>
    item.title.toLowerCase().includes(query.toLowerCase()),
  );
  const active = isActiveRun(currentRun);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      {sidebarOpen && (
        <button
          className="drawer-backdrop"
          aria-label="关闭侧栏"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        className={`sidebar ${sidebarOpen ? "is-open" : ""}`}
        aria-label="会话侧栏"
      >
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            if (!sending) selectConversation(null);
          }}
        >
          <span className="brand-mark">
            <Compass size={25} strokeWidth={1.7} />
          </span>
          <span>
            <strong>
              逛搭 <b>GoMate</b>
            </strong>
            <small>本地生活规划助手</small>
          </span>
        </a>
        <button
          className="button primary new-chat"
          onClick={() => selectConversation(null)}
          disabled={sending}
        >
          <Plus size={19} /> 新建会话
        </button>
        <div className="sidebar-label">
          <span>历史会话</span>
          <span>{conversations.length || ""}</span>
        </div>
        {user && (
          <label className="search-field">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索会话"
              aria-label="搜索会话"
            />
          </label>
        )}
        <nav className="conversation-list" aria-label="历史会话">
          {!user ? (
            <div className="sidebar-empty">
              <MessageCircle size={25} strokeWidth={1.3} />
              <p>尚未登录</p>
              <span>登录后可查看历史会话。</span>
            </div>
          ) : filtered.length === 0 && !listing ? (
            <div className="sidebar-empty">
              <MessageCircle size={25} />
              <p>{query ? "未找到匹配的会话" : "暂无会话"}</p>
              <span>
                {query
                  ? "请尝试其他关键词。"
                  : "发送一条消息，会话就会保存在这里。"}
              </span>
            </div>
          ) : (
            filtered.map((item) => (
              <div
                className={`conversation-item ${selected === item.id ? "selected" : ""}`}
                key={item.id}
              >
                <button
                  className="conversation-select"
                  disabled={sending}
                  onClick={() => selectConversation(item.id)}
                  aria-current={selected === item.id ? "page" : undefined}
                  aria-label={`打开会话：${item.title}`}
                  title={item.title}
                >
                  <MessageCircle size={17} />
                  <span>
                    <strong>{item.title}</strong>
                    <small>{timeLabel(item.created_at)}</small>
                  </span>
                </button>
                <button
                  className="icon-button delete-conversation"
                  aria-label={`删除会话：${item.title}`}
                  disabled={sending}
                  onClick={() => setDeleting(item)}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))
          )}
          {listing && (
            <div className="list-loading">
              <LoaderCircle size={17} className="spin" /> 正在加载会话…
            </div>
          )}
          {hasMore && !listing && (
            <button
              className="text-button load-more"
              onClick={moreConversations}
            >
              加载更多会话
            </button>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="account-row">
            <span className="avatar">
              {user ? (
                user.username.slice(0, 1).toUpperCase()
              ) : (
                <UserRound size={18} />
              )}
            </span>
            <div>
              <strong>{user?.username || "未登录"}</strong>
              <small>{user ? "已登录" : "登录后可保存会话"}</small>
            </div>
            {user ? (
              <button
                className="icon-button"
                aria-label="退出登录"
                onClick={logout}
              >
                <LogOut size={17} />
              </button>
            ) : (
              <button
                className="text-button"
                onClick={() => setAuthOpen(true)}
                disabled={checking}
              >
                {checking ? "验证中" : "登录"}
              </button>
            )}
          </div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="icon-button mobile-menu"
              aria-label="打开会话侧栏"
              aria-expanded={sidebarOpen}
              onClick={() => setSidebarOpen(true)}
            >
              <Menu size={21} />
            </button>
            <span className="workspace-label">生活规划</span>
            <span className="beta-tag">预览版</span>
          </div>
          <div className="topbar-right">
            <button className="city-button knowledge-button" aria-label="知识库" onClick={() => user ? setKnowledgeOpen(true) : setAuthOpen(true)}>
              <BookOpen size={16} /> <span>知识库</span>
            </button>
            <button
              className="city-button"
              disabled={sending}
              onClick={() => {
                setCityDraft(city);
                setCityOpen(true);
              }}
            >
              <MapPin size={16} />
              {city || "选择城市"}
              <ChevronDown size={14} />
            </button>
            <span
              className={`connection ${service}`}
              title={service === "online" ? "服务连接正常" : "正在检查服务连接"}
            >
              <span />
              {service === "online"
                ? "已连接"
                : service === "offline"
                  ? "连接中断"
                  : "连接中"}
            </span>
            <button
              className="icon-button toggle-plan"
              aria-label="打开行程预览"
              aria-expanded={planOpen}
              onClick={() => setPlanOpen(true)}
            >
              <PanelRightOpen size={20} />
            </button>
          </div>
        </header>
        <div className="workspace-body">
          <main id="main-content" className="conversation-main">
            {notice && (
              <div className="notice" role="alert">
                <Info size={18} />
                <span>{notice}</span>
                <button
                  className="icon-button"
                  aria-label="关闭提示"
                  onClick={() => setNotice("")}
                >
                  <X size={16} />
                </button>
              </div>
            )}
            <div className="chat-scroll">
              {historyLoading ? (
                <div className="history-loading" role="status">
                  <LoaderCircle className="spin" size={24} />
                  正在加载消息…
                </div>
              ) : messages.length === 0 ? (
                <Welcome onSuggestion={suggest} />
              ) : (
                <div className="message-list">
                  <div className="conversation-intro">
                    <Compass size={17} /> 会话记录
                  </div>
                  {messages.map((message) => (
                    <article
                      className={`message ${message.role}`}
                      key={message.id}
                    >
                      <span className="message-avatar">
                        {message.role === "user" ? (
                          <UserRound size={18} />
                        ) : (
                          <Compass size={19} />
                        )}
                      </span>
                      <div>
                        <span className="message-author">
                          {message.role === "user" ? "你" : "逛搭"}
                        </span>
                        <p>{message.content}</p>
                        <MessageSources message={message} />
                      </div>
                    </article>
                  ))}
                  {currentRun && <RunStatus run={currentRun} />}
                  <div ref={bottom} />
                </div>
              )}
            </div>
            <div className="composer-area">
              <form className="composer" onSubmit={send}>
                <label className="sr-only" htmlFor="message-input">
                  输入出行需求
                </label>
                <textarea
                  ref={composer}
                  id="message-input"
                  value={draft}
                  maxLength={15000}
                  rows={2}
                  onChange={(event) =>
                    setDrafts((items) => ({
                      ...items,
                      [draftKey]: event.target.value,
                    }))
                  }
                  onKeyDown={composerKey}
                   placeholder="输入问题，或描述城市、时间、人数和预算。"
                  disabled={sending || checking}
                />
                <div className="composer-toolbar">
                  <span>
                    <Compass size={15} /> 出行需求
                  </span>
                  <div>
                    {draft.length > 14000 && (
                      <span className="char-count">{draft.length}/15000</span>
                    )}
                    {active ? (
                      <button
                        className="send-button cancel"
                        type="button"
                        aria-label="取消当前任务"
                        onClick={cancelRun}
                        disabled={cancelling}
                      >
                        <Square size={16} fill="currentColor" />
                      </button>
                    ) : (
                      <button
                        className="send-button"
                        type="submit"
                        aria-label={user ? "发送消息" : "登录后发送"}
                        disabled={
                          !draft.trim() || sending || checking || historyLoading
                        }
                      >
                        {sending ? (
                          <LoaderCircle size={20} className="spin" />
                        ) : (
                          <ArrowUp size={22} />
                        )}
                      </button>
                    )}
                  </div>
                </div>
              </form>
              <p className="composer-footnote">
                {user ? "消息及相关知识片段将发送至 DeepSeek" : "登录后可进行文字聊天"}
                <span>·</span>Enter 发送，Shift + Enter 换行
              </p>
            </div>
          </main>
          {planOpen && (
            <button
              className="plan-backdrop"
              aria-label="收起行程预览"
              onClick={() => setPlanOpen(false)}
            />
          )}
          <PlanPanel
            city={city}
            mobile={planOpen}
            onClose={() => setPlanOpen(false)}
          />
        </div>
      </div>
      {authOpen && (
        <AuthDialog
          onClose={() => setAuthOpen(false)}
          onAuthenticated={authenticate}
        />
      )}
      {cityOpen && (
        <Dialog title="选择出发城市" onClose={() => setCityOpen(false)}>
          <p className="muted">
            城市将与出行需求一起保存。
          </p>
          <form
            className="city-form"
            onSubmit={(event) => {
              event.preventDefault();
              setCity(cityDraft.trim());
              setCityOpen(false);
            }}
          >
            <label>
              城市
              <input
                autoFocus
                value={cityDraft}
                onChange={(event) => setCityDraft(event.target.value)}
                maxLength={40}
                placeholder="例如：杭州"
              />
            </label>
            <div className="city-chips">
              {["杭州", "上海", "北京", "成都", "广州", "深圳"].map((value) => (
                <button
                  type="button"
                  key={value}
                  onClick={() => setCityDraft(value)}
                  className={cityDraft === value ? "selected" : ""}
                >
                  {value}
                </button>
              ))}
            </div>
            <button className="button primary" type="submit">
              {cityDraft.trim() ? "确认" : "暂不选择"}
            </button>
          </form>
        </Dialog>
      )}
      {knowledgeOpen && user && (
        <KnowledgeDialog key={`${user.id}:${selected}`} api={api} sessionId={selected}
          onClose={() => setKnowledgeOpen(false)} onChanged={() => setHistoryVersion((value) => value + 1)} onError={handleError} />
      )}
      {deleting && (
        <Dialog
          title="删除会话？"
          onClose={() => setDeleting(null)}
          busy={deleteBusy}
        >
          <p className="muted">
            「{deleting.title}」和其中的消息将被删除，删除后无法恢复。
          </p>
          <div className="dialog-actions">
            <button
              className="button secondary"
              onClick={() => setDeleting(null)}
              disabled={deleteBusy}
            >
              保留会话
            </button>
            <button
              className="button danger"
              onClick={deleteConversation}
              disabled={deleteBusy}
            >
              {deleteBusy ? "删除中…" : "确认删除"}
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function RunStatus({ run }: { run: Run }) {
  const active = isActiveRun(run);
  const scaffold = run.error_code === "WORKFLOW_NOT_IMPLEMENTED";
  const saved = scaffold || run.status === "succeeded";
  let title = "处理未完成";
  let text = run.error_message || "消息已保存，可重新发送问题。";
  if (active) {
    title = "正在生成回复";
    text = "正在调用 DeepSeek，可以取消当前回复。";
  } else if (scaffold) {
    title = "需求已保存";
    text =
      "当前支持保存需求和查看历史会话，暂不支持生成完整行程。你可以继续补充出发时间、预算等信息。";
  } else if (run.status === "cancelled") { title = "回复已取消"; text = "消息已保存，可以继续提问。"; }
  else if (run.status === "waiting_user") {
    title = "请补充信息";
    text = "请补充出发时间、地点或预算。";
  } else if (run.status === "succeeded") {
    title = "回复已完成";
    text = "对话已保存。";
  }
  return (
    <div
      className={`run-status ${saved ? "saved" : active ? "pending" : "stopped"}`}
      role="status"
    >
      <span className="run-icon">
        {active ? (
          <LoaderCircle size={19} className="spin" />
        ) : saved ? (
          <Check size={19} />
        ) : (
          <Info size={19} />
        )}
      </span>
      <div>
        <strong>{title}</strong>
        <p>{text}</p>
      </div>
    </div>
  );
}
