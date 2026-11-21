import {
  Coffee,
  Compass,
  Footprints,
  Sparkles,
  Trees,
  Utensils,
} from "lucide-react";

const suggestions = [
  {
    icon: Trees,
    label: "把周末交给自然",
    text: "周末想在附近轻松玩半天，少走路，再找一家好吃的店。",
    tone: "green",
  },
  {
    icon: Coffee,
    label: "找一段慢下来的时光",
    text: "想找个安静的地方喝咖啡、看看书，顺便逛逛周边。",
    tone: "amber",
  },
  {
    icon: Utensils,
    label: "从一顿好饭开始",
    text: "帮我安排下班后的两小时，吃点好的，再去附近散散步。",
    tone: "blue",
  },
];

export function Welcome({
  onSuggestion,
}: {
  onSuggestion: (value: string) => void;
}) {
  return (
    <section className="welcome" aria-label="开始规划">
      <div className="welcome-badge">
        <Sparkles size={15} /> 日常，也值得认真期待
      </div>
      <div className="welcome-symbol" aria-hidden="true">
        <Compass size={44} strokeWidth={1.4} />
      </div>
      <h1>
        把今天，安排得<span>刚刚好。</span>
      </h1>
      <p className="welcome-copy">
        一次说走就走，一顿心心念念。
        <br />
        把想法告诉逛搭，一起找找生活的好去处。
      </p>
      <div className="suggestion-grid">
        {suggestions.map(({ icon: Icon, label, text, tone }) => (
          <button
            className={`suggestion ${tone}`}
            key={label}
            onClick={() => onSuggestion(text)}
          >
            <span className="suggestion-icon">
              <Icon size={22} strokeWidth={1.7} />
            </span>
            <strong>{label}</strong>
            <span>{text}</span>
          </button>
        ))}
      </div>
      <div className="welcome-caption">
        <Footprints size={15} /> 远近都好，喜欢最重要
      </div>
    </section>
  );
}
