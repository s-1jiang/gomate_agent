"""Explicit opt-in live provider test, using only a public synthetic Hangzhou request."""

import argparse
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.integrations.deepseek import DeepSeekClient
from app.main import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="gomate-live-itinerary-") as directory:
        config = Settings(database_path=Path(directory) / "test.db")
        if not all(
            (
                config.deepseek_api_key.get_secret_value(),
                config.amap_web_service_key.get_secret_value(),
            )
        ):
            raise SystemExit("Missing configured model or map credential; no provider call made")
        app = create_app(config)
        outputs = []

        class CapturedModel(DeepSeekClient):
            async def complete(self, *model_args, **model_kwargs):
                value = await super().complete(*model_args, **model_kwargs)
                outputs.append(value)
                if args.output:
                    args.output.with_suffix(".diagnostic.json").write_text(
                        json.dumps(
                            {"public_example_outputs": outputs}, ensure_ascii=False, indent=2
                        ),
                        encoding="utf-8",
                    )
                return value

        app.state.chat.model = CapturedModel(config)
        with TestClient(app) as client:
            credentials = {"username": "live_smoke", "password": "local-test-account-only"}
            client.post("/api/v1/auth/register", json=credentials)
            token = client.post("/api/v1/auth/login", json=credentials).json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            session = client.post("/api/v1/conversations", json={}, headers=headers).json()["id"]
            path = f"/api/v1/conversations/{session}/messages"
            accepted = client.post(
                path,
                headers=headers,
                json={
                    "client_message_id": "public-example",
                    "content": (
                        "明天在杭州9点到17点游玩，两个人，从杭州东站出发并返回，公共交通，"
                        "想轻松逛西湖并安排午餐。请给出每段时间、停留多久和每一站的玩法。"
                    ),
                },
            )
            run = client.get("/api/v1/runs/" + accepted.json()["id"], headers=headers).json()
            print(
                json.dumps(
                    {
                        key: run[key]
                        for key in (
                            "status",
                            "error_code",
                            "error_message",
                            "tool_calls",
                            "external_requests",
                            "llm_calls",
                        )
                    },
                    ensure_ascii=False,
                )
            )
            history = client.get(path, headers=headers).json()
            if len(history) < 2:
                if args.output:
                    args.output.write_text(
                        json.dumps(
                            {"run": run, "public_example_outputs": outputs},
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                raise SystemExit("Live test did not produce a reply")
            message = history[-1]
            result = message.get("map_result")
            if args.output:
                args.output.write_text(
                    json.dumps(message, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            if not result or not result.get("itinerary"):
                print(message["content"])
                raise SystemExit(
                    "Live response requires clarification or did not yield an itinerary"
                )
            plan = result["itinerary"]
            print(plan["title"])
            for day in plan["days"]:
                for stop in day["stops"]:
                    print(
                        stop["arrival_at"],
                        stop["departure_at"],
                        stop["name"],
                        stop["duration_minutes"],
                    )
                print("Finish:", day["finish_at"], "Spare minutes:", day["spare_minutes"])
    print("PASS: live public-example itinerary, no existing user data used")


if __name__ == "__main__":
    main()
