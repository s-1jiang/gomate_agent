import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ApiClient, type MapSearchResult } from "../api";
import { ItineraryAnswer } from "../components/ItineraryAnswer";
import fixture from "./fixtures/itinerary.json";

const result = fixture as unknown as MapSearchResult;

it("renders travel and stay times, activities, evidence and the map between stops", () => {
  const api = new ApiClient("fake");
  const request = vi.spyOn(api, "mapConfig");
  render(<ItineraryAnswer api={api} result={result} />);
  expect(screen.getByRole("heading", { name: "杭州半日安排" })).toBeVisible();
  expect(screen.getByText("09:30—10:45")).toHaveTextContent("游玩 · 75 分钟");
  expect(screen.getByText(/12:45 返回出发点/)).toBeVisible();
  expect(screen.getAllByText(/另留 10 分钟缓冲/)).toHaveLength(3);
  const first = screen.getByRole("heading", { name: "[M1] 湖畔公园" }).closest("article")!;
  const second = screen.getByRole("heading", { name: "[M2] 文化公园" }).closest("article")!;
  const map = screen.getByRole("img", { name: /地点位置示意/ }).closest("figure")!;
  expect(first.compareDocumentPosition(map) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(map.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(within(first).getByRole("link", { name: "[W1]" })).toHaveAttribute("href", "https://parks.example.org/A");
  expect(within(first).getByText("玩法建议")).toBeVisible();
  expect(within(first).getByText("待确认")).toBeVisible();
  expect(request).not.toHaveBeenCalled();
  expect(document.querySelector('script[src*="amap"]')).toBeNull();
});

it("keeps the inline schematic and source links usable when the interactive map is not configured", async () => {
  const api = new ApiClient("fake");
  vi.spyOn(api, "mapConfig").mockResolvedValue({ provider: "amap", display_enabled: false,
    search_enabled: true, js_key: "", default_city: "", security_proxy: "/api/v1/maps/_AMapService" });
  const user = userEvent.setup();
  render(<ItineraryAnswer api={api} result={result} />);
  await user.click(screen.getByRole("button", { name: "加载交互地图" }));
  expect(await screen.findByRole("status")).toHaveTextContent("交互底图尚未配置");
  expect(screen.getByRole("img", { name: /地点位置示意/ })).toBeVisible();
  expect(screen.getAllByRole("link", { name: "在地图中查看" })).toHaveLength(2);
});

it("does not invent connecting route geometry when the provider returned no paths", () => {
  const withoutPaths = structuredClone(result);
  withoutPaths.itinerary!.days[0].legs.forEach((leg) => { leg.paths = []; });
  withoutPaths.itinerary!.days[0].stops.push({ ...withoutPaths.itinerary!.days[0].stops[0],
    kind: "break", arrival_at: "2026-11-25T13:00:00+08:00", departure_at: "2026-11-25T13:30:00+08:00" });
  const { container } = render(<ItineraryAnswer api={new ApiClient("fake")} result={withoutPaths} />);
  expect(container.querySelectorAll("polyline")).toHaveLength(0);
  expect(container.querySelectorAll('svg[role="img"] circle')).toHaveLength(3);
});
