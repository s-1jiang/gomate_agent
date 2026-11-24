import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import type { MapPlace, MapSearchResult } from "../api";
import { NearbyAnswer } from "../components/NearbyAnswer";

function place(id: string, name: string, agent: "dining" | "activity" = "dining"): MapPlace {
  return { provider: "amap", poi_id: id, name, city_code: "0411", city: "大连市", district: "", address: "示例路",
    category: "服务", source_ref: `amap:poi:${id}`, fetched_at: "2026-11-24T00:00:00Z", label: id,
    task_id: "task", agent, location: { longitude: 121.5, latitude: 38.8, coordinate_system: "GCJ02" } };
}

export const nearbyFixture: MapSearchResult = {
  status: "approved", city: "大连市", review_rounds: 0, events: [], searched_at: "2026-11-24T00:00:00Z",
  places: [place("M1", "凌水餐厅"), place("M2", "凌水台球", "activity"), place("M3", "一二九餐厅")],
  recommendation_groups: [
    { area: place("area-1", "大连理工大学(凌水校区)"), answer: "先吃饭，再打台球。", place_ids: ["M1", "M2"],
      route: { origin_poi_id: "M1", destination_poi_id: "M2", mode: "walking", distance_meters: 700, walking_meters: 700,
        duration_seconds: 600, instructions: ["沿示例路前往台球馆"], paths: [], source_ref: "amap:route:walking", fetched_at: "2026-11-24T00:00:00Z" } },
    { area: place("area-2", "大连理工大学一二九校区"), answer: "也可以选这一片区域。", place_ids: ["M3"], route: null },
  ],
};

it("separates recommendations by campus and preserves map links and observed walking time", () => {
  const { container } = render(<NearbyAnswer result={nearbyFixture} />);
  const first = screen.getByRole("heading", { name: "大连理工大学(凌水校区)" }).closest("section")!;
  const second = screen.getByRole("heading", { name: "大连理工大学一二九校区" }).closest("section")!;
  expect(within(first).getByText("[M1] 凌水餐厅")).toBeVisible();
  expect(within(first).getByText(/步行约 10 分钟/)).toBeVisible();
  expect(within(first).queryByText("[M3] 一二九餐厅")).not.toBeInTheDocument();
  expect(within(second).getByText("[M3] 一二九餐厅")).toBeVisible();
  expect(within(first).getAllByRole("link", { name: "在地图中查看" })[0]).toHaveAttribute("href", expect.stringContaining("uri.amap.com/marker"));
  expect(screen.queryByText(/请补充|POI|Agent|GCJ/)).not.toBeInTheDocument();
  expect(container.querySelector('script[src*="amap"]')).toBeNull();
});

it("renders the complete model-selected shop list without a two-place display limit", () => {
  const result = structuredClone(nearbyFixture);
  result.places = Array.from({ length: 12 }, (_, index) => place(`M${index + 1}`, `备选咖啡馆${index + 1}`));
  result.recommendation_groups = [{ ...result.recommendation_groups![0], place_ids: result.places.map((p) => p.poi_id), route: null }];
  render(<NearbyAnswer result={result} />);
  expect(screen.getAllByRole("link", { name: "在地图中查看" })).toHaveLength(12);
  expect(screen.getByText("[M12] 备选咖啡馆12")).toBeVisible();
  expect(screen.queryByText(/两处间步行/)).not.toBeInTheDocument();
});
