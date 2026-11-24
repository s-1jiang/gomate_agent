import type { MapSearchResult } from "../api";

export function NearbyAnswer({ result }: { result: MapSearchResult }) {
  return <section className="itinerary-answer nearby-answer" aria-label="周边推荐">
    {result.recommendation_groups?.map((group) => <section className="itinerary-day" key={group.area.poi_id}>
      <h3>{group.area.name}</h3>
      <p>{group.answer}</p>
      <ol className="nearby-places">{group.place_ids.map((id) => {
        const place = result.places.find((item) => item.poi_id === id);
        if (!place) return null;
        const params = new URLSearchParams({ position: `${place.location.longitude},${place.location.latitude}`, name: place.name, coordinate: "gaode", callnative: "0" });
        return <li className="itinerary-stop" key={id}>
          <strong>[{place.label}] {place.name}</strong>
          <p>{place.address || "地址暂缺"}</p>
          <a href={`https://uri.amap.com/marker?${params}`} target="_blank" rel="noopener noreferrer">在地图中查看</a>
        </li>;
      })}</ol>
      {group.route && <div className="itinerary-travel">
        <p>两处间步行约 {Math.max(1, Math.ceil(group.route.duration_seconds / 60))} 分钟 · {(group.route.distance_meters / 1000).toFixed(1)} 公里</p>
        {!!group.route.instructions.length && <details><summary>步行详情</summary><ol>{group.route.instructions.map((text, i) => <li key={i}>{text}</li>)}</ol></details>}
      </div>}
    </section>)}
    <small>地点与路线来源：高德地图。营业情况请向商家确认。</small>
  </section>;
}
