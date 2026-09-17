"""Validate the Google OAuth client credentials in `.env`.

Google only authenticates the client *after* it checks the authorization code, so a
deliberately bogus code is enough to tell the two failure modes apart:

    invalid_client  -> the client ID / secret pair is wrong (nothing else matters yet)
    invalid_grant   -> credentials are GOOD; Google got past client auth and only
                       objected to the fake code

Run from the repo root with the project venv:

    .venv/Scripts/python scripts/check_google_oauth.py

Exit code 0 means the credentials are usable; 1 means they are not. The secret is
never printed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://localhost:8000/api/auth/google/callback"
# Google's secrets start with "GOCSPX-" and have consistently been 35 chars, but the
# length is NOT a documented contract, so it is reported as a hint, never a verdict.
TYPICAL_SECRET_LEN = 35


def main() -> int:
    settings = get_settings()
    client_id = settings.google_client_id
    client_secret = settings.google_client_secret

    print(f"env file      : {settings.model_config.get('env_file')}")
    print(f"client id set : {bool(client_id)}")
    print(f"secret set    : {bool(client_secret)} (len {len(client_secret)})")

    if not client_id or not client_secret:
        print("\nFAIL: google_enabled is false because one of the two values is empty.")
        print("      Fill GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env, then restart.")
        return 1

    if len(client_secret) != TYPICAL_SECRET_LEN:
        print(
            f"\nWARNING: secret is {len(client_secret)} chars; Google's are usually "
            f"{TYPICAL_SECRET_LEN}. A short value suggests a truncated or masked copy."
        )

    try:
        response = httpx.post(
            TOKEN_ENDPOINT,
            data={
                "code": "bogus-code-credential-probe",
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        print(f"\nFAIL: could not reach Google's token endpoint ({type(exc).__name__}).")
        return 1

    try:
        error = response.json().get("error", "")
    except ValueError:
        error = ""

    print(f"\nhttp status   : {response.status_code}")
    print(f"google error  : {error or '(none)'}")

    if error == "invalid_grant":
        print("\nOK: client ID and secret are a valid pair (only the fake code was refused).")
        print("    The consent round-trip should now work.")
        return 0

    if error == "invalid_client":
        print("\nFAIL: Google rejected the credentials.")
        print("      'The provided client secret is invalid' means either the secret is")
        print("      mistyped/incomplete, or it belongs to a DIFFERENT OAuth client than the")
        print("      client ID. Note that the Cloud Console masks a secret after creation,")
        print("      so a partially-visible value is a common cause. Fix by opening")
        print("      Credentials -> your OAuth client and using 'Reset secret' to get a fresh")
        print("      complete value, then paste it into .env and re-run this check.")
        return 1

    print(f"\nUNEXPECTED: {response.text[:300]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
