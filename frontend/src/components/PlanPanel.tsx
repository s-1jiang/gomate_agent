import { Clock3, MapPin, Route, Wallet, X } from "lucide-react";

export function PlanPanel({
  city,
  mobile,
  onClose,
}: {
  city: string;
  mobile: boolean;
  onClose: () => void;
}) {
  return (
    <aside
      className={`plan-panel ${mobile ? "is-open" : ""}`}
      aria-label="行程预览"
    >
      <div className="panel-heading">
        <div>
          <span className="eyebrow">YOUR NEXT LITTLE ADVENTURE</span>
          <h2>行程预览</h2>
        </div>
        <button
          className="icon-button panel-close"
          onClick={onClose}
          aria-label="关闭行程预览"
        >
          <X size={20} />
        </button>
      </div>
      <div className="route-illustration" aria-hidden="true">
        <div className="map-grid" />
        <svg viewBox="0 0 280 190">
          <path
            className="route-shadow"
            d="M49 135C68 145 82 117 109 118S122 64 154 70S192 107 227 46"
          />
          <path
            className="route-line"
            d="M49 135C68 145 82 117 109 118S122 64 154 70S192 107 227 46"
          />
          <circle
            cx="49"
            cy="135"
            r="8"
            fill="#126957"
            stroke="white"
            strokeWidth="4"
          />
          <circle
            cx="154"
            cy="70"
            r="7"
            fill="#dfaa4b"
            stroke="white"
            strokeWidth="4"
          />
          <circle
            cx="227"
            cy="46"
            r="9"
            fill="#126957"
            stroke="white"
            strokeWidth="4"
          />
        </svg>
        <div className="illustration-pin">
          <MapPin size={20} />
        </div>
        <span className="illustration-label">下一站，值得期待</span>
      </div>
      <div className="empty-plan">
        <h3>好行程，始于一个想法</h3>
        <p>
          告诉我你想怎么度过这段时光。
          <br />
          地点、路线和安排，将在这里相遇。
        </p>
      </div>
      <div className="plan-facts">
        <div>
          <span>
            <MapPin size={17} /> 出发城市
          </span>
          <strong>{city || "由你决定"}</strong>
        </div>
        <div>
          <span>
            <Clock3 size={17} /> 时间安排
          </span>
          <strong>等待你的想法</strong>
        </div>
        <div>
          <span>
            <Wallet size={17} /> 出行预算
          </span>
          <strong>按你的节奏</strong>
        </div>
      </div>
      <div className="feature-note">
        <Route size={19} />
        <div>
          <strong>先把想法留下来</strong>
          <p>目前可保存需求、查看历史会话。完整行程生成功能正在准备中。</p>
        </div>
      </div>
      <div className="panel-bottom">
        <span className="tiny-compass">✦</span> 少一点纠结，多一点出发。
      </div>
    </aside>
  );
}
