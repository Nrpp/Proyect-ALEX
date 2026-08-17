#!/usr/bin/env python3
"""
One-time helper to generate a VAPID key pair for Web Push notifications
(used by the web console's "Add to Home Screen" PWA install, so
notifications can reach a phone - including an iPhone, iOS 16.4+ - even
while the console isn't open).

Uses only what's already a project dependency (py-vapid, which pywebpush
pulls in) - no extra pip install needed beyond ALEX's own requirements.txt.

Usage:
    python3 scripts/gen_vapid_keys.py

Prints three lines to paste into your .env:
    ALEX_VAPID_PUBLIC_KEY=...
    ALEX_VAPID_PRIVATE_KEY=...
    ALEX_VAPID_CONTACT_EMAIL=you@example.com   (fill in your own address)

The private key must stay secret (it's what proves push messages come
from your server) - never commit it, never paste it anywhere but your
own .env. The public key is safe to expose; the browser needs it to
create a subscription.
"""
from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02
from py_vapid.utils import b64urlencode


def main() -> None:
    vapid = Vapid02()
    vapid.generate_keys()

    private_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    print("Paste these into your .env:\n")
    print(f"ALEX_VAPID_PUBLIC_KEY={b64urlencode(public_raw)}")
    print(f"ALEX_VAPID_PRIVATE_KEY={b64urlencode(private_raw)}")
    print("ALEX_VAPID_CONTACT_EMAIL=you@example.com   # <- change this to your own address")


if __name__ == "__main__":
    main()
