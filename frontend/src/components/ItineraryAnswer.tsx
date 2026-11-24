import { useId, useMemo, useState } from "react";
import { Clock3, MapPin, Navigation } from "lucide-react";
import { ApiClient, errorMessage, type MapConfig, type MapPlace, type MapSearchResult, type ScheduledDay, type ScheduledStop, type ScheduledLeg, type WebEvidence } from "../api";
import { PlaceMap } from "./PlaceMap";

const transport = { walking: "步行", driving: "驾车", transit: "公共交通" };
const time = (value: string) => new Date(value).toLocaleTimeString("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false });
const date = (value: string) => new Date(value).toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai", month: "long", day: "numeric", weekday: "short" });
const distance = (meters: number) => meters < 1000 ? `${meters} 米` : `${(meters / 1000).toFixed(1)} 公里`;

function sourceLink(source: WebEvidence) {
  try { return new URL(source.url).protocol === "https:" ? source.url : undefined; } catch { return undefined; }
}

function StopCard({ stop, sources, place }: { stop: ScheduledStop; sources: WebEvidence[]; place?: MapPlace }) {
  const practical = stop.practical_info.filter((info) => info.evidence_ids.some((id) =>
    sources.some((source) => source.label === id && source.poi_id === stop.poi_id)));
  function references(ids: string[]) {
    return ids.map((id) => {
      const source = sources.find((item) => item.label === id && item.poi_id === stop.poi_id);
      return source ? <a className="evidence-link" key={id} href={sourceLink(source)} target="_blank" rel="noopener noreferrer">[{id}]</a> : null;
    });
  }
  const params = place ? new URLSearchParams({ position: `${place.location.longitude},${place.location.latitude}`, name: place.name, coordinate: "gaode", callnative: "0" }) : null;
  return <article className="itinerary-stop">
    <div className="timeline-time">{time(stop.arrival_at)}—{time(stop.departure_at)}<span>{stop.kind === "meal" ? "用餐" : stop.kind === "break" ? "休息" : "游玩"} · {stop.duration_minutes} 分钟</span></div>
    <h4><span className="source-tag">[{stop.label}]</span> {stop.name}</h4>
    <strong className="stop-label">建议玩法</strong>
    <ul>{stop.activities.map((activity, index) => <li key={index}>{activity.text} {references(activity.evidence_ids)}</li>)}</ul>
    {!!practical.length && <div className="stop-practical">{practical.map((info, index) => <p key={index}>{info.text} {references(info.evidence_ids)}</p>)}</div>}
    {params && <div className="stop-location"><MapPin size={14} /><span>{place?.address || "地址暂缺"}</span><a href={`https://uri.amap.com/marker?${params}`} target="_blank" rel="noopener noreferrer">在地图中查看</a></div>}
  </article>;
}

function TravelCard({ leg }: { leg: ScheduledLeg }) {
  return <article className="itinerary-travel">
    <Navigation size={16} /><div><strong>{time(leg.start_at)}—{time(leg.end_at)} · {transport[leg.mode]}</strong>
      <p>{leg.origin_name} → {leg.destination_name}</p>
      <span>交通约 {leg.duration_minutes} 分钟 · {distance(leg.distance_meters)} · 另留 {leg.buffer_minutes} 分钟缓冲</span>
      <details><summary>交通详情 [{leg.label}]</summary><ol>{leg.instructions.map((text, index) => <li key={index}>{text}</li>)}</ol>{leg.mode === "transit" && <small>步行 {distance(leg.walking_meters)}</small>}</details>
    </div>
  </article>;
}

function JourneyMap({ api, places, day }: { api: ApiClient; places: MapPlace[]; day: ScheduledDay }) {
  const [config, setConfig] = useState<MapConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const paths = useMemo(() => day.legs.flatMap((leg) => leg.paths), [day]);
  const id = useId();
  const all = [...places.map((place) => [place.location.longitude, place.location.latitude]), ...paths.flat()];
  const minX = Math.min(...all.map((point) => point[0])), maxX = Math.max(...all.map((point) => point[0]));
  const minY = Math.min(...all.map((point) => point[1])), maxY = Math.max(...all.map((point) => point[1]));
  const scale = Math.min(500 / Math.max(maxX - minX, 0.005), 120 / Math.max(maxY - minY, 0.005));
  const project = (point: number[]) => [300 + (point[0] - (minX + maxX) / 2) * scale, 95 - (point[1] - (minY + maxY) / 2) * scale];
  async function show() {
    setLoading(true); setNotice("");
    try { const value = await api.mapConfig(); if (value.display_enabled) setConfig(value); else setNotice("地图暂时无法打开，可通过地点链接查看。"); }
    catch (error) { setNotice(errorMessage(error)); }
    finally { setLoading(false); }
  }
  return <figure className="journey-map">
    <figcaption><MapPin size={16} /><strong>行程地图</strong></figcaption>
    {config ? <PlaceMap config={config} places={places} selectedId={selected} onSelect={setSelected} visible paths={paths} /> : <>
      <svg viewBox="0 0 600 200" role="img" aria-labelledby={id}><title id={id}>地点位置示意</title>
        <rect width="600" height="200" rx="12" fill="#f2f6f1" />
        {paths.filter((path) => path.length > 1).map((path, index) => <polyline key={index} points={path.map((point) => project(point).join(",")).join(" ")} fill="none" stroke="#7b9b87" strokeWidth="3" />)}
        {places.map((place) => { const [x, y] = project([place.location.longitude, place.location.latitude]); return <g key={place.poi_id}><circle cx={x} cy={y} r="12" fill="#426c54" /><text x={x} y={y + 4} textAnchor="middle" fontSize="9" fill="white">{place.label}</text><text x={x} y={y + 28} textAnchor="middle" fontSize="11" fill="#34513e">{place.name.slice(0, 13)}</text></g>; })}
      </svg>
      <div className="journey-map-footer"><small>位置示意</small><button className="button secondary" onClick={() => void show()} disabled={loading}>{loading ? "正在加载…" : "查看地图"}</button></div>
    </>}
    {notice && <p role="status">{notice}</p>}
  </figure>;
}

export function ItineraryAnswer({ result, api }: { result: MapSearchResult; api: ApiClient }) {
  const plan = result.itinerary;
  if (!plan) return null;
  const modes = [...new Set(plan.days.flatMap((day) => day.legs.map((leg) => leg.mode)))];
  const travelMode = (modes.length ? modes : [plan.request.mode]).map((mode) => transport[mode]).join(" + ");
  return <section className="itinerary-answer" aria-label="完整游玩行程">
    <header><h2>{plan.title}</h2>
      <div className="itinerary-facts"><span><Clock3 size={14} />{plan.days.length} 天</span><span>{travelMode}</span>{plan.request.party_size > 1 && <span>{plan.request.party_size} 人</span>}{plan.request.budget_fen !== null && <span>{plan.request.budget_scope === "per_person" ? "人均预算" : "总预算"} ¥{(plan.request.budget_fen / 100).toFixed(0)}</span>}</div>
    </header>
    {plan.days.map((day, index) => {
      const rows = [...day.stops.map((stop) => ({ at: stop.arrival_at, stop, leg: null })), ...day.legs.map((leg) => ({ at: leg.start_at, leg, stop: null }))].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
      const points = [...new Set(day.stops.map((stop) => stop.poi_id))].map((poiId) => result.places.find((place) => place.poi_id === poiId)).filter((place): place is MapPlace => !!place);
      if (plan.origin) points.unshift({ ...plan.origin, label: "起点", task_id: "origin", agent: "places" });
      const firstStop = rows.findIndex((row) => row.stop);
      return <section className="itinerary-day" key={day.start_at} aria-label={`第${index + 1}天行程`}>
        <h3>第 {index + 1} 天 <span>{date(day.start_at)}</span></h3>
        <p className="day-overview">{time(day.start_at)} {plan.origin ? "出发" : "开始游玩"} · {time(day.finish_at)} {plan.request.return_to_origin ? "返回出发点" : "结束"}</p>
        <div className="itinerary-timeline">{rows.map((row, rowIndex) => <div key={`${row.at}:${rowIndex}`}>
          {row.stop ? <StopCard stop={row.stop} place={result.places.find((place) => place.poi_id === row.stop?.poi_id)} sources={plan.web_sources} /> : row.leg && <TravelCard leg={row.leg} />}
          {rowIndex === firstStop && <JourneyMap api={api} places={points} day={day} />}
        </div>)}</div>
      </section>;
    })}
    <p className="itinerary-notes">出发前请确认开放和预约信息。{plan.request.budget_fen !== null && "具体费用以现场或官方信息为准。"}</p>
    {!!plan.web_sources.length && <section className="web-evidence" aria-label="参考来源"><h3>参考来源</h3>{plan.web_sources.map((source) => <details key={source.label}><summary>[{source.label}] {source.title}</summary><a href={sourceLink(source)} target="_blank" rel="noopener noreferrer">打开原文</a><blockquote>{source.excerpt}</blockquote></details>)}</section>}
  </section>;
}
