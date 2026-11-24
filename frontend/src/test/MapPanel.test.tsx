import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ApiClient, type MapConfig, type MapSearchResult } from "../api";
import { MapPanel } from "../components/MapPanel";
import { PlaceMap } from "../components/PlaceMap";
import { loadMapSdk } from "../mapSdk";

vi.mock("../mapSdk", () => ({ loadMapSdk: vi.fn() }));

const config: MapConfig = {
  provider: "amap", search_enabled: true, display_enabled: false, js_key: "",
  security_proxy: "/api/v1/maps/_AMapService", default_city: "杭州",
};
const result: MapSearchResult = {
  status: "approved", city: "杭州", review_rounds: 1, searched_at: "2026-11-24T00:00:00Z",
  events: [{ stage: "revise", agent: "supervisor", task_id: "task-1", task_version: 2,
    summary: "退回修改：请缩小搜索区域" }],
  places: [{ provider: "amap", poi_id: "B001", name: "河边咖啡", city_code: "0571",
    city: "杭州", district: "西湖区", address: "示例路 10 号", category: "咖啡馆",
    location: { longitude: 120.15, latitude: 30.25, coordinate_system: "GCJ02" },
    source_ref: "amap:poi:B001", fetched_at: "2026-11-24T00:00:00Z", label: "M1",
    task_id: "task-1", agent: "dining" }],
};

function api(value = config) {
  const client = new ApiClient("fake-token");
  vi.spyOn(client, "mapConfig").mockResolvedValue(value);
  return client;
}

it("sends a city and keyword to the chat workflow and uses provider data in source cards", async () => {
  const search = vi.fn();
  const user = userEvent.setup();
  render(<MapPanel api={api()} city="杭州" result={result} mobile={false} signedIn busy={false}
    onClose={vi.fn()} onSearch={search} onError={vi.fn()} />);
  await user.type(screen.getByLabelText("地点关键词"), "咖啡馆");
  await user.click(screen.getByRole("button", { name: "搜索地点" }));
  expect(search).toHaveBeenCalledWith("咖啡馆", "杭州");
  expect(screen.getByText("[M1] 河边咖啡")).toBeInTheDocument();
  await user.click(screen.getByText("来源与查询时间"));
  expect(screen.getByText("高德地图 · POI：B001")).toBeVisible();
  const link = screen.getByRole("link", { name: "在高德查看" });
  expect(link.getAttribute("href")).toContain("https://uri.amap.com/marker?");
  expect(link.getAttribute("href")).toContain("120.15%2C30.25");
  await user.click(screen.getByText("任务分发与审查记录"));
  expect(screen.getByText("退回修改：请缩小搜索区域")).toBeVisible();
  expect(loadMapSdk).not.toHaveBeenCalled();
});

it("never shows rejected candidates at the revision limit", async () => {
  render(<MapPanel api={api()} city="杭州" result={{ ...result, status: "revision_limit", places: [] }}
    mobile={false} signedIn busy={false} onClose={vi.fn()} onSearch={vi.fn()} onError={vi.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent("仍未通过审查");
  expect(screen.queryByText("[M1] 河边咖啡")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "在高德查看" })).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText("搜索城市")).toHaveValue("杭州"));
});

it("renders authoritative coordinates and keeps marker/card selection synchronized", async () => {
  const add = vi.fn(), remove = vi.fn(), fit = vi.fn(), center = vi.fn(), destroy = vi.fn();
  const clicks: (() => void)[] = [];
  const map = { add, remove, setFitView: fit, setZoomAndCenter: center, destroy };
  const marker = vi.fn(function (_options: Record<string, unknown>) { return { on: (_name: string, action: () => void) => clicks.push(action) }; });
  const polyline = vi.fn(function (_options: Record<string, unknown>) { return {}; });
  const sdk = { Map: vi.fn(function () { return map; }), Marker: marker, Polyline: polyline };
  vi.stubGlobal("AMap", sdk);
  vi.mocked(loadMapSdk).mockResolvedValue(sdk);
  const select = vi.fn();
  const view = render(<PlaceMap config={{ ...config, display_enabled: true }} places={result.places}
    selectedId="B001" onSelect={select} visible paths={[[[120.15, 30.25], [120.16, 30.26]]]} />);
  await waitFor(() => expect(marker).toHaveBeenCalled());
  expect(marker.mock.calls[0][0]).toMatchObject({ position: [120.15, 30.25], title: "河边咖啡" });
  expect(center).toHaveBeenCalledWith(15, [120.15, 30.25]);
  expect(polyline).toHaveBeenCalledWith(expect.objectContaining({ path: [[120.15, 30.25], [120.16, 30.26]] }));
  clicks[0]();
  expect(select).toHaveBeenCalledWith("B001");
  view.unmount();
  expect(destroy).toHaveBeenCalledOnce();
});
