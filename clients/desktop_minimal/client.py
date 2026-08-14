"""
ALEX minimal desktop client.

Connects to ALEX over the WebSocket protocol described in
`clients/protocol.md`, and shows an always-on-top overlay popup whenever a
notification arrives that meets the configured minimum priority - the first
implementation of the "overlay/popup" requirement. Runs on Windows, macOS
and Linux (uses only the Python standard library's Tk binding + websockets
+ requests), and is deliberately minimal: no tray icon, no chat window yet.
It exists to prove the client protocol end-to-end and to be the base a
richer native Windows client can follow later (same WS/REST contract).

Run:
    pip install -r requirements.txt
    cp .env.example .env   # then edit ALEX_HOST / ALEX_TOKEN
    python client.py
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import socket
import threading
import tkinter as tk

import requests
import websockets
from dotenv import load_dotenv

load_dotenv()

ALEX_HOST = os.environ.get("ALEX_HOST", "raspberrypi.local")
ALEX_PORT = os.environ.get("ALEX_PORT", "8787")
ALEX_TOKEN = os.environ.get("ALEX_TOKEN", "")
MIN_POPUP_PRIORITY = int(os.environ.get("ALEX_CLIENT_MIN_PRIORITY", "1"))
CLIENT_ID = f"desktop-{socket.gethostname()}"

WS_URL = f"ws://{ALEX_HOST}:{ALEX_PORT}/ws?token={ALEX_TOKEN}&client_id={CLIENT_ID}"
API_BASE = f"http://{ALEX_HOST}:{ALEX_PORT}"

PRIORITY_COLORS = {0: "#3b3f45", 1: "#2f6fed", 2: "#e0952a", 3: "#d63b3b"}
PRIORITY_AUTO_DISMISS_MS = {0: 6000, 1: 12000, 2: None, 3: None}

notification_queue: "queue.Queue[dict]" = queue.Queue()


def _headers() -> dict:
    return {"Authorization": f"Bearer {ALEX_TOKEN}"} if ALEX_TOKEN else {}


async def _ws_loop() -> None:
    backoff = 2
    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                print(f"[alex-client] connected to {ALEX_HOST}:{ALEX_PORT}")
                backoff = 2
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("type") == "notification":
                        notification_queue.put(data["notification"])
                    elif data.get("type") == "hello":
                        print(f"[alex-client] hello from {data.get('assistant_name')}")
        except Exception as e:
            print(f"[alex-client] connection error: {e} - retrying in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def _start_ws_thread() -> None:
    def runner():
        asyncio.run(_ws_loop())

    threading.Thread(target=runner, daemon=True).start()


class OverlayManager:
    """Stacks small always-on-top popups in the top-right corner of the screen."""

    def __init__(self, root: tk.Tk):
        self._root = root
        self._stack_offset = 20

    def show(self, notification: dict) -> None:
        priority = int(notification.get("priority", 1))
        if priority < MIN_POPUP_PRIORITY:
            print(f"[alex-client] (below threshold, logged only) {notification.get('title')}: {notification.get('body')}")
            return

        width, height = 320, 130
        popup = tk.Toplevel(self._root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        screen_w = popup.winfo_screenwidth()
        y = self._stack_offset
        popup.geometry(f"{width}x{height}+{screen_w - width - 20}+{y}")
        self._stack_offset += height + 12

        bg = PRIORITY_COLORS.get(priority, "#2f6fed")
        popup.configure(bg=bg)

        tk.Label(
            popup, text=notification.get("title", ""), bg=bg, fg="white",
            font=("Segoe UI", 11, "bold"), wraplength=300, justify="left", anchor="w",
        ).pack(fill="x", padx=12, pady=(12, 2))
        tk.Label(
            popup, text=notification.get("body", ""), bg=bg, fg="white",
            font=("Segoe UI", 9), wraplength=300, justify="left", anchor="w",
        ).pack(fill="x", padx=12)

        btn_frame = tk.Frame(popup, bg=bg)
        btn_frame.pack(fill="x", padx=12, pady=10)

        closed = {"done": False}

        def close():
            if closed["done"]:
                return
            closed["done"] = True
            popup.destroy()
            self._stack_offset -= height + 12

        actions = notification.get("actions") or [{"id": "dismiss", "label": "Descartar"}]
        for action in actions:
            def handler(a=action):
                self._handle_action(notification, a)
                close()

            tk.Button(btn_frame, text=action.get("label", "OK"), command=handler).pack(side="left", padx=4)

        auto_dismiss = PRIORITY_AUTO_DISMISS_MS.get(priority)
        if auto_dismiss:
            popup.after(auto_dismiss, close)

    def _handle_action(self, notification: dict, action: dict) -> None:
        notif_id = notification.get("id")
        action_id = action.get("action_id")
        approved = action.get("id") == "confirm"
        try:
            if action_id:
                requests.post(
                    f"{API_BASE}/actions/{action_id}/confirm",
                    json={"approved": approved}, headers=_headers(), timeout=5,
                )
            if notif_id:
                requests.post(
                    f"{API_BASE}/notifications/{notif_id}/status",
                    json={"status": "acted" if approved else "dismissed"}, headers=_headers(), timeout=5,
                )
        except requests.RequestException as e:
            print(f"[alex-client] failed to report action to server: {e}")


def main() -> None:
    if not ALEX_TOKEN:
        print("[alex-client] WARNING: ALEX_TOKEN is empty - set it in .env")

    root = tk.Tk()
    root.withdraw()  # no main window - this client is overlay-only for now

    _start_ws_thread()
    manager = OverlayManager(root)

    def poll_queue():
        try:
            while True:
                manager.show(notification_queue.get_nowait())
        except queue.Empty:
            pass
        root.after(200, poll_queue)

    root.after(200, poll_queue)
    root.mainloop()


if __name__ == "__main__":
    main()
