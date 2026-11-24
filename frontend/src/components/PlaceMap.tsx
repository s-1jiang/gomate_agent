import { useEffect, useRef, useState } from "react";
import type { MapConfig, MapPlace } from "../api";
import { loadMapSdk, type MapInstance, type MarkerInstance } from "../mapSdk";

export function PlaceMap({ config, places, selectedId, onSelect, visible, paths = [] }: {
  config: MapConfig; places: MapPlace[]; selectedId: string | null;
  onSelect: (id: string) => void; visible: boolean; paths?: [number, number][][];
}) {
  const node = useRef<HTMLDivElement>(null);
  const map = useRef<MapInstance | null>(null);
  const markers = useRef<MarkerInstance[]>([]);
  const lines = useRef<object[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const choose = useRef(onSelect);
  choose.current = onSelect;
  useEffect(() => {
    let disposed = false;
    loadMapSdk(config).then((sdk) => {
      if (disposed || !node.current) return;
      map.current = new sdk.Map(node.current, { zoom: 12, viewMode: "2D", resizeEnable: true });
      setReady(true);
    }).catch((caught) => { if (!disposed) setError(caught.message); });
    return () => { disposed = true; map.current?.destroy(); map.current = null; };
  }, [config]);
  useEffect(() => {
    if (!ready || !map.current || !window.AMap) return;
    const instance = map.current;
    instance.remove(markers.current);
    markers.current = places.map((place) => {
      const label = document.createElement("span");
      label.className = "place-marker";
      label.textContent = place.label;
      const marker = new window.AMap!.Marker({
        position: [place.location.longitude, place.location.latitude],
        content: label, title: place.name,
      });
      marker.on("click", () => choose.current(place.poi_id));
      return marker;
    });
    instance.add(markers.current);
    if (markers.current.length) instance.setFitView(markers.current, false, [30, 30, 30, 30], 15);
  }, [places, ready]);
  useEffect(() => {
    const instance = map.current, Polyline = window.AMap?.Polyline;
    if (!ready || !instance || !Polyline) return;
    instance.remove(lines.current);
    lines.current = paths.filter((path) => path.length > 1).map((path) => new Polyline({
      path, strokeColor: "#477b64", strokeWeight: 5, strokeOpacity: 0.8,
    }));
    instance.add(lines.current);
  }, [paths, ready]);
  useEffect(() => {
    const place = places.find((item) => item.poi_id === selectedId);
    if (ready && place) map.current?.setZoomAndCenter(15, [place.location.longitude, place.location.latitude]);
  }, [selectedId, ready, places]);
  useEffect(() => {
    if (ready && visible && markers.current.length)
      map.current?.setFitView(markers.current, true, [30, 30, 30, 30], 15);
  }, [visible, ready]);
  return <div className="place-map-wrap">
    <div className="place-map" ref={node} aria-label="高德地点地图" />
    {error && <p role="alert" className="map-error">{error} 可通过地点链接查看。</p>}
    {!ready && !error && <p role="status">正在加载高德地图…</p>}
  </div>;
}
