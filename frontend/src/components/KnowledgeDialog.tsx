import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiClient, errorMessage, type KnowledgeDocument } from "../api";
import { Dialog } from "./Dialog";

export function KnowledgeDialog({ api, sessionId, onClose, onChanged, onError }: {
  api: ApiClient;
  sessionId: string | null;
  onClose: () => void;
  onChanged: () => void;
  onError: (error: unknown) => void;
}) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const [content, setContent] = useState("");
  const [scope, setScope] = useState<"session" | "user">(sessionId ? "session" : "user");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const controller = useRef(new AbortController());
  useEffect(() => {
    const abort = new AbortController();
    controller.current = abort;
    api.knowledge(sessionId, abort.signal).then((items) => {
      if (!abort.signal.aborted) setDocuments(items);
    }).catch((error) => {
      if (!abort.signal.aborted) { setNotice(errorMessage(error)); onError(error); }
    }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [api, sessionId, onError]);

  async function add(event: FormEvent) {
    event.preventDefault();
    if (busy || !content.trim()) return;
    const signal = controller.current.signal;
    setBusy(true);
    setNotice("");
    try {
      const item = await api.addKnowledge({
        title: title.trim(), source_ref: source.trim(), content,
        scope, session_id: scope === "session" ? sessionId : null,
      }, signal);
      if (signal.aborted) return;
      setDocuments((items) => [item, ...items]);
      setTitle(""); setSource(""); setContent("");
      setNotice("资料已加入，可在后续对话中检索。");
      onChanged();
    } catch (error) {
      if (!signal.aborted) { setNotice(errorMessage(error)); onError(error); }
    } finally { if (!signal.aborted) setBusy(false); }
  }
  async function remove(id: string) {
    const signal = controller.current.signal;
    setBusy(true);
    try {
      await api.deleteKnowledge(id, signal);
      if (signal.aborted) return;
      setDocuments((items) => items.filter((item) => item.id !== id));
      setDeleting(null);
      setNotice("资料已删除，不再参与检索。");
      onChanged();
    } catch (error) {
      if (!signal.aborted) { setNotice(errorMessage(error)); onError(error); }
    } finally { if (!signal.aborted) setBusy(false); }
  }
  return (
    <Dialog title="知识库" onClose={onClose} busy={busy} className="knowledge-dialog">
      <p className="muted">加入 TXT、Markdown 或粘贴文本。聊天时仅检索你的用户知识库及当前会话资料，并显示来源标签。</p>
      <p className="muted">提问时，会将当前会话上下文和召回片段发送给 DeepSeek 生成回答。</p>
      <form className="knowledge-form" onSubmit={add}>
        <label>选择文本文件
          <input type="file" accept=".txt,.md,.markdown,text/plain,text/markdown" disabled={busy} onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            if (!/\.(txt|md|markdown)$/i.test(file.name) || file.size > 300000) {
              setNotice("请选择不超过 300 KB 的 TXT 或 Markdown 文件。"); return;
            }
            const signal = controller.current.signal;
            try {
              const text = await file.text();
              if (signal.aborted) return;
              if (text.length > 100000) { setNotice("资料正文最多 100000 字符。"); return; }
              setTitle(file.name); setSource(file.name); setContent(text);
            } catch { if (!signal.aborted) setNotice("文件读取失败，请重新选择。"); }
          }} />
        </label>
        <label>资料名称<input required value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} disabled={busy} /></label>
        <label>来源说明<input value={source} maxLength={512} placeholder="例如：周末笔记.md（用户提供的来源名称）" onChange={(event) => setSource(event.target.value)} disabled={busy} /></label>
        <label>可见范围<select value={scope} onChange={(event) => setScope(event.target.value as "session" | "user")} disabled={busy}>
          <option value="session" disabled={!sessionId}>仅当前会话</option>
          <option value="user">我的所有会话</option>
        </select></label>
        <label>资料正文<textarea required value={content} maxLength={100000} rows={5} onChange={(event) => setContent(event.target.value)} disabled={busy} /></label>
        <button className="button primary" type="submit" disabled={busy || !title.trim() || !content.trim()}>{busy ? "处理中…" : "加入知识库"}</button>
      </form>
      {notice && <p role="status">{notice}</p>}
      <h3>可检索资料</h3>
      {loading ? <p>正在读取资料…</p> : !documents.length ? <p className="muted">暂无资料。不添加资料也可以进行文字聊天。</p> : (
        <ul className="knowledge-list">{documents.map((item) => <li key={item.id}>
          <strong>{item.title}</strong>
          <small>{item.scope === "session" ? "当前会话" : "用户知识库"} · {item.chunk_count} 个片段 · 版本 {item.document_version}</small>
          {deleting === item.id ? <div className="dialog-actions">
            <button className="button secondary" disabled={busy} onClick={() => setDeleting(null)}>保留资料</button>
            <button className="button danger" disabled={busy} onClick={() => void remove(item.id)}>确认删除资料</button>
          </div> : <button className="text-button" disabled={busy} aria-label={`删除资料：${item.title}`} onClick={() => setDeleting(item.id)}>删除</button>}
        </li>)}</ul>
      )}
    </Dialog>
  );
}
