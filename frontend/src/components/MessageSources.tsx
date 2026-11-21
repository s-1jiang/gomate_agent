import type { Message } from "../api";

export function MessageSources({ message }: { message: Message }) {
  if (message.role !== "assistant") return null;
  const sources = message.sources || [];
  if (!sources.length) {
    return message.retrieval_status === "no_matches" ? (
      <small className="source-note">未检索到相关资料，本次回复由模型生成。</small>
    ) : null;
  }
  return (
    <section className="message-sources" aria-label="检索来源">
      <strong>检索来源 <small>· 本地关键词检索</small></strong>
      {sources.map((source) => (
        <details key={source.label} className="source-card">
          <summary>
            <span className="source-tag">[{source.label}]</span>
            <span>{source.available ? source.title : "来源已删除，内容不可查看"}</span>
            <small>{source.cited ? "正文已引用" : "已召回，正文未引用"}</small>
          </summary>
          {source.available && (
            <div className="source-detail">
              <p>{source.source_ref} · 第 {source.start_line}–{source.end_line} 行 · 版本 {source.document_version}</p>
              <blockquote>{source.excerpt}</blockquote>
              <p>{source.scope === "session" ? "当前会话资料" : "用户知识库"} · 检索时间：{source.retrieved_at ? new Date(source.retrieved_at).toLocaleString() : "未知"}</p>
              <dl>
                <dt>文档 ID</dt><dd>{source.document_id}</dd>
                <dt>片段 ID</dt><dd>{source.chunk_id}</dd>
                <dt>片段 SHA-256</dt><dd>{source.content_hash}</dd>
                <dt>文档 SHA-256</dt><dd>{source.document_hash}</dd>
              </dl>
            </div>
          )}
        </details>
      ))}
      <small className="source-note">标签表示可追溯的检索原文；模型是否正确理解仍需核对。</small>
    </section>
  );
}
