import type { Message } from "../api";

export function MessageSources({ message }: { message: Message }) {
  if (message.role !== "assistant") return null;
  const sources = message.sources || [];
  if (!sources.length) return null;
  return (
    <section className="message-sources" aria-label="检索来源">
      <strong>检索来源</strong>
      {sources.map((source) => (
        <details key={source.label} className="source-card">
          <summary>
            <span className="source-tag">[{source.label}]</span>
            <span>{source.available ? source.title : "来源已删除，内容不可查看"}</span>
            <small>{source.cited ? "正文引用" : "参考资料"}</small>
          </summary>
          {source.available && (
            <div className="source-detail">
              <p>{source.source_ref} · 第 {source.start_line}–{source.end_line} 行</p>
              <blockquote>{source.excerpt}</blockquote>
            </div>
          )}
        </details>
      ))}
    </section>
  );
}
