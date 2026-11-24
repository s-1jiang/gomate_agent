import { useEffect, useState, type FormEvent } from "react";
import { MapPin, Search, X } from "lucide-react";
import { ApiClient, errorMessage, type MapConfig, type MapSearchResult } from "../api";
import { PlaceMap } from "./PlaceMap";

export function MapPanel({ api, city, result, mobile, signedIn, busy, onClose, onSearch, onError }: {
  api: ApiClient; city: string; result: MapSearchResult | null; mobile: boolean;
  signedIn: boolean; busy: boolean; onClose: () => void;
  onSearch: (keyword: string, city: string) => void; onError: (error: unknown) => void;
}) {
  const [keyword, setKeyword] = useState("");
  const [searchCity, setSearchCity] = useState(city);
  const [config, setConfig] = useState<MapConfig | null>(null);
  const [display, setDisplay] = useState(false);
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  useEffect(() => { setSearchCity(city); }, [city]);
  useEffect(() => {
    if (!signedIn) return;
    const abort = new AbortController();
    api.mapConfig(abort.signal).then((value) => {
      if (abort.signal.aborted) return;
      setConfig(value);
      setSearchCity((previous) => previous || value.default_city);
    }).catch((error) => { if (!abort.signal.aborted) { setNotice(errorMessage(error)); onError(error); } });
    return () => abort.abort();
  }, [api, signedIn, onError]);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !keyword.trim() || !searchCity.trim()) return;
    onSearch(keyword.trim(), searchCity.trim());
  }
  const places = result?.places || [];
  return <aside className={`plan-panel map-panel ${mobile ? "is-open" : ""}`} aria-label="地点搜索与地图">
    <div className="panel-heading"><h2>地点搜索</h2>
      <button className="icon-button panel-close" aria-label="关闭地点地图" onClick={onClose}><X size={20} /></button>
    </div>
    <form className="map-search-form" onSubmit={submit}>
      <label>搜索城市<input value={searchCity} maxLength={80} placeholder="例如：杭州" onChange={(event) => setSearchCity(event.target.value)} required disabled={busy} /></label>
      <label>地点关键词<input value={keyword} maxLength={80} placeholder="例如：咖啡馆、公园" onChange={(event) => setKeyword(event.target.value)} required disabled={busy} /></label>
      <button className="button primary" disabled={busy || !keyword.trim() || !searchCity.trim()} type="submit"><Search size={16} />{signedIn ? "搜索地点" : "登录后搜索地点"}</button>
    </form>
    <p className="map-helper">这里查询地点。需要完整行程时，在对话中告诉我出发点、时间和游玩偏好。</p>
    {notice && <p role="alert" className="map-error">{notice}</p>}
    {config && !config.search_enabled && <p className="map-helper">地点搜索暂时不可用，请稍后再试。</p>}
    {places.length > 0 && <>
      {display && config?.display_enabled ? <PlaceMap config={config} places={places} selectedId={selectedId} onSelect={setSelectedId} visible={mobile} /> :
        config?.display_enabled ? <button className="button secondary load-map" onClick={() => setDisplay(true)}>显示高德地图</button> : <p className="map-helper">可点击地点链接查看地图。</p>}
      <p className="map-helper">{result?.city}</p>
    </>}
    {!result && <div className="empty-map"><MapPin size={30} /><p>输入城市和关键词，或在对话中提出地点需求。</p></div>}
    {result?.status === "no_results" && <p role="status">没有查到合适地点，可以调整城市或关键词。</p>}
    {result?.status === "revision_limit" && <p role="status">暂时没找到合适的地点，请调整区域或要求。</p>}
    {result?.status === "needs_clarification" && <p role="status">请在对话中补充需要的信息。</p>}
    <ol className="place-list">{places.map((place) => {
      const params = new URLSearchParams({ position: `${place.location.longitude},${place.location.latitude}`, name: place.name, coordinate: "gaode", callnative: "0", src: "gomate" });
      return <li key={place.poi_id} className={selectedId === place.poi_id ? "selected" : ""}>
        <button className="place-select" onClick={() => setSelectedId(place.poi_id)}><strong>[{place.label}] {place.name}</strong><span>{place.address || "地址暂缺"}</span><small>{place.city} {place.district} · {place.category}</small></button>
        <a href={`https://uri.amap.com/marker?${params}`} target="_blank" rel="noopener noreferrer">在高德查看</a>
        <small className="place-source">来源：高德地图</small>
      </li>;
    })}</ol>
  </aside>;
}
