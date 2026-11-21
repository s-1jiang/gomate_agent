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
    label: "周末半日游",
    text: "周末在附近玩半天，尽量少走路，并安排一顿午餐。",
    tone: "green",
  },
  {
    icon: Coffee,
    label: "咖啡馆和周边散步",
    text: "找一家安静的咖啡馆，喝咖啡、看书，再逛逛周边。",
    tone: "amber",
  },
  {
    icon: Utensils,
    label: "晚餐和散步",
    text: "安排下班后的两小时，包括晚餐和附近散步。",
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
        <Sparkles size={15} /> 本地生活规划
      </div>
      <div className="welcome-symbol" aria-hidden="true">
        <Compass size={44} strokeWidth={1.4} />
      </div>
      <h1>
        描述你的<span>出行需求</span>
      </h1>
      <p className="welcome-copy">
        填写出发城市、时间、人数和预算，
        <br />
        也可以从下方示例开始。
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
        <Footprints size={15} /> 点击示例可填入输入框
      </div>
    </section>
  );
}
