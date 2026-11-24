import type { MapConfig } from "./api";

export interface MapInstance {
  add(markers: object[]): void;
  remove(markers: object[]): void;
  setFitView(markers: MarkerInstance[], immediately: boolean, padding: number[], maxZoom: number): void;
  setZoomAndCenter(zoom: number, center: number[]): void;
  destroy(): void;
}
export interface MarkerInstance { on(name: string, handler: () => void): void; }
export interface AMapSdk {
  Map: new (container: HTMLElement, options: Record<string, unknown>) => MapInstance;
  Marker: new (options: Record<string, unknown>) => MarkerInstance;
  Polyline?: new (options: Record<string, unknown>) => object;
}
declare global {
  interface Window {
    AMap?: AMapSdk;
    _AMapSecurityConfig?: { serviceHost: string };
  }
}

let loading: Promise<AMapSdk> | null = null;
export function loadMapSdk(config: MapConfig): Promise<AMapSdk> {
  if (window.AMap) return Promise.resolve(window.AMap);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    window._AMapSecurityConfig = { serviceHost: window.location.origin + config.security_proxy };
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(config.js_key)}`;
    script.async = true;
    let settled = false;
    const fail = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      script.remove();
      loading = null;
      reject(new Error("地图暂时无法加载，请稍后再试。"));
    };
    const timer = setTimeout(fail, 12000);
    script.onerror = fail;
    script.onload = () => {
      if (settled) return;
      if (!window.AMap) { fail(); return; }
      settled = true;
      clearTimeout(timer);
      resolve(window.AMap);
    };
    document.head.appendChild(script);
  });
  return loading;
}
