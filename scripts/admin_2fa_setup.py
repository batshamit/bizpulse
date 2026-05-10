#!/usr/bin/env python
"""Generate a TOTP secret + provisioning URI for admin 2FA.

Usage:
    .venv/bin/python scripts/admin_2fa_setup.py [--issuer BizPulse] [--account amit@dei]

Prints:
  1. The base32 secret (paste into .env as BIZPULSE_ADMIN_TOTP_SECRET)
  2. A scannable otpauth:// URI you can paste into Google Authenticator /
     1Password / Authy / Bitwarden as a manual-entry fallback
  3. An ASCII-art QR if `qrcode` is installed (pip install qrcode)

After enabling, every admin login requires both BIZPULSE_ADMIN_KEY AND a
6-digit code from your authenticator app. Without TOTP set, only the
admin key is required (back-compat).
"""

from __future__ import annotations

import argparse
import sys

try:
    import pyotp  # type: ignore[import-untyped]
except ImportError:
    sys.stderr.write(
        "pyotp not installed. Install with: .venv/bin/pip install pyotp\n"
    )
    sys.exit(2)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--issuer", default="BizPulse")
    p.add_argument("--account", default="admin")
    args = p.parse_args()

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=args.account, issuer_name=args.issuer)

    print("=" * 60)
    print("BIZPULSE_ADMIN_TOTP_SECRET=" + secret)
    print("=" * 60)
    print()
    print("Provisioning URI (paste into your authenticator if QR doesn't work):")
    print("  " + uri)
    print()

    try:
        import qrcode  # type: ignore[import-untyped]
        qr = qrcode.QRCode(border=1)
        qr.add_data(uri)
        qr.make(fit=True)
        print("Scan this QR with your authenticator app:")
        qr.print_ascii(invert=True)
    except ImportError:
        print("(install `qrcode` for an ASCII QR: .venv/bin/pip install qrcode)")

    print()
    print("Next steps:")
    print("  1. Add BIZPULSE_ADMIN_TOTP_SECRET=... to /raid/amit/mylearning/bizpulse/.env")
    print("  2. Restart FastAPI (tmux kill-window -t bizpulse:api; tmux new-window -t bizpulse -n api ...)")
    print("  3. The admin login form will now require a 6-digit TOTP code")


if __name__ == "__main__":
    main()
