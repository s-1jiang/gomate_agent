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
  expect(within(first).getByText("建议玩法")).toBeVisible();
  expect(within(first).getByText("找合适的位置坐一会儿")).toBeVisible();
  expect(screen.queryByText("出发前确认开放与预约")).not.toBeInTheDocument();
  expect(request).not.toHaveBeenCalled();
  expect(document.querySelector('script[src*="amap"]')).toBeNull();
});

it("keeps the inline schematic and source links usable when the interactive map is not configured", async () => {
  const api = new ApiClient("fake");
  vi.spyOn(api, "mapConfig").mockResolvedValue({ provider: "amap", display_enabled: false,
    search_enabled: true, js_key: "", default_city: "", security_proxy: "/api/v1/maps/_AMapService" });
  const user = userEvent.setup();
  render(<ItineraryAnswer api={api} result={result} />);
  await user.click(screen.getByRole("button", { name: "查看地图" }));
  expect(await screen.findByRole("status")).toHaveTextContent("地图暂时无法打开，可通过地点链接查看");
  expect(screen.getByRole("img", { name: /地点位置示意/ })).toBeVisible();
  expect(screen.getAllByRole("link", { name: "在地图中查看" })).toHaveLength(2);
});

it("hides legacy assumptions and internal explanations while preserving useful trip details", () => {
  const legacy = structuredClone(result);
  const plan = legacy.itinerary!;
  plan.request.assumptions = ["人数未说明，暂按1人", "交通方式未说明，默认公共交通"];
  plan.summary = "本方案由 Supervisor 分派 Agent，已通过校验。";
  plan.warnings = ["未启用联网检索：需要配置 Tavily API Key。"];
  plan.days[0].stops[0].reason = "根据 POI 编号和默认参数生成。";
  plan.days[0].stops[0].practical_info = [{ text: "入口需要提前预约", evidence_ids: ["W1"] }];
  render(<ItineraryAnswer api={new ApiClient("fake")} result={legacy} />);
  expect(screen.queryByText(/本次采用的假设|人数未说明|默认公共交通/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Supervisor|Agent|校验|Tavily|API Key|POI|GCJ-02|余量/)).not.toBeInTheDocument();
  expect(screen.getByText("入口需要提前预约")).toBeVisible();
  expect(screen.getByText("出发前请确认开放和预约信息。")).toBeVisible();
  expect(screen.getByText("09:30—10:45")).toHaveTextContent("75 分钟");
  expect(screen.getByRole("region", { name: "参考来源" })).toHaveTextContent("[W1]");
});

it("labels the first stop as the start of the visit when no departure point was provided", () => {
  const withoutOrigin = structuredClone(result);
  withoutOrigin.itinerary!.origin = null;
  withoutOrigin.itinerary!.request.return_to_origin = false;
  render(<ItineraryAnswer api={new ApiClient("fake")} result={withoutOrigin} />);
  expect(screen.getByText(/09:00 开始游玩/)).toBeVisible();
});

it("shows each actual transport mode and walking directions in a mixed itinerary", async () => {
  const mixed = structuredClone(result);
  const leg = mixed.itinerary!.days[0].legs[1];
  Object.assign(leg, { mode: "walking", distance_meters: 1418, walking_meters: 1418,
    duration_minutes: 19, duration_seconds: 1134, instructions: ["沿步道走到下一站"] });
  const user = userEvent.setup();
  render(<ItineraryAnswer api={new ApiClient("fake")} result={mixed} />);
  expect(screen.getByText("公共交通 + 步行")).toBeVisible();
  const travel = screen.getByText("湖畔公园 → 文化公园").closest("article")!;
  expect(travel).toHaveTextContent("步行");
  expect(travel).toHaveTextContent("19 分钟 · 1.4 公里");
  await user.click(within(travel).getByText("交通详情 [T2]"));
  expect(within(travel).getByText("沿步道走到下一站")).toBeVisible();
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
