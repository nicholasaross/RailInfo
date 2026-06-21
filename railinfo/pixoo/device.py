"""Minimal client for the Divoom Pixoo 64 local HTTP API.

The Pixoo connects over Wi-Fi (the USB lead is power only) and exposes a JSON API on
port 80 at ``/post``. We implement just what we need — pushing a 64x64 RGB frame and a
couple of settings — directly with httpx, so there is no extra dependency and we own the
behaviour. Frames are sent via ``Draw/SendHttpGif`` (one frame per call); the device
ignores a repeated ``PicID``, so it is incremented on every push.

``discover_host`` uses Divoom's cloud endpoint, which returns the devices that share the
caller's LAN — handy because the Pixoo's IP is otherwise hard to find.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
from PIL import Image

DIVOOM_DISCOVERY_URL = "https://app.divoom-gz.com/Device/ReturnSameLANDevice"
SIZE = 64


class PixooError(RuntimeError):
    """A friendly, user-facing error for a Pixoo request failure."""


def discover_devices(*, timeout: float = 15.0) -> list[dict[str, Any]]:
    try:
        response = httpx.post(DIVOOM_DISCOVERY_URL, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PixooError(f"Pixoo LAN discovery failed: {exc}") from exc
    return data.get("DeviceList") or []


def discover_host() -> str | None:
    """Return the IP of the first Pixoo on this LAN, or None."""
    for device in discover_devices():
        ip = device.get("DevicePrivateIP")
        if ip:
            return ip
    return None


class PixooDevice:
    def __init__(self, host: str, *, timeout: float = 10.0) -> None:
        self.host = host
        self._url = f"http://{host}/post"
        # A persistent keep-alive connection — the Pixoo's per-request HTTP cost
        # dominates frame rate, so reusing the socket roughly doubles throughput.
        self._client = httpx.Client(timeout=timeout)
        self._pic_id = 1
        self.reset_gif_id()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PixooDevice":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def reset_gif_id(self) -> None:
        self._post({"Command": "Draw/ResetHttpGifId"})
        self._pic_id = 1

    def set_brightness(self, level: int) -> None:
        self._post(
            {"Command": "Channel/SetBrightness", "Brightness": max(0, min(100, level))}
        )

    def push_image(self, image: Image.Image) -> None:
        if image.size != (SIZE, SIZE):
            image = image.resize((SIZE, SIZE))
        data = image.convert("RGB").tobytes()  # row-major RGB, SIZE*SIZE*3 bytes
        self._post(
            {
                "Command": "Draw/SendHttpGif",
                "PicNum": 1,
                "PicWidth": SIZE,
                "PicOffset": 0,
                "PicID": self._pic_id,
                "PicSpeed": 1000,
                "PicData": base64.b64encode(data).decode("ascii"),
            }
        )
        self._pic_id += 1

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = payload.get("Command")
        try:
            response = self._client.post(self._url, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PixooError(
                f"Pixoo request '{command}' to {self.host} failed: {exc}"
            ) from exc
        if body.get("error_code", 0) != 0:
            raise PixooError(
                f"Pixoo '{command}' returned error_code {body['error_code']}."
            )
        return body
