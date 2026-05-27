import httpx

from app.schemas import DetectionEvent


async def send_detection_webhook(url: str, event: DetectionEvent) -> tuple[bool, str | None]:
    payload = event.model_dump(mode="json")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        return True, None
    except Exception as exc:  # pragma: no cover - exact HTTP exceptions are not important here.
        return False, str(exc)

