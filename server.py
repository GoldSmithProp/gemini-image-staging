"""
Gemini Image Staging MCP Server
================================

A minimal remote MCP server exposing ONE tool, `stage_image`, that sends a
photo + an editing instruction to Google's Gemini image model
(gemini-2.5-flash-image) and returns the edited image.

Built for the "virtual-staging" Claude skill: Claude sends the original room
photo (as base64) plus a staging prompt built from the skill's edit-prompt
template, and gets back a furnished version of the same room.

--------------------------------------------------------------------------
DEPLOYMENT
--------------------------------------------------------------------------
1. Set the environment variable GEMINI_API_KEY (from https://aistudio.google.com/apikey).
2. Optionally set MCP_SHARED_SECRET to a random string of your choosing —
   if set, callers must send it as a Bearer token in the Authorization
   header. Strongly recommended since this server takes no other auth by
   default and, once deployed, its URL is reachable by anyone who has it.
3. Optionally set PORT (defaults to 8080 — Cloud Run/Render's convention).
4. Run:  python3 server.py
   This starts a streamable-HTTP MCP server at http://0.0.0.0:$PORT/mcp
5. Deploy that to any host with a public HTTPS URL (Render, Cloud Run,
   Railway, Fly.io, etc.) — MCP remote connectors require HTTPS.
6. In claude.ai: Settings -> Connectors -> Add custom connector, and paste
   the deployed URL + your MCP_SHARED_SECRET as the bearer token if you set
   one.
--------------------------------------------------------------------------
"""

import base64
import os
import sys
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MCP_SHARED_SECRET = os.environ.get("MCP_SHARED_SECRET", "")
PORT = int(os.environ.get("PORT", "8080"))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-image")
GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

if not GEMINI_API_KEY:
    print(
        "WARNING: GEMINI_API_KEY is not set. The server will start but "
        "every stage_image call will fail until it is configured.",
        file=sys.stderr,
    )

mcp = FastMCP(
    name="gemini-image-staging",
    stateless_http=True,  # simpler for a single-tool utility server
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
def stage_image(
    image_base64: str,
    mime_type: str,
    prompt: str,
) -> dict[str, Any]:
    """
    Edit a real-estate photo with Gemini's image model: adds furniture/decor
    per `prompt` while preserving the room's structure, per the caller's
    instructions embedded in the prompt itself.

    Args:
        image_base64: The original photo, base64-encoded (no data: prefix).
        mime_type: The image's MIME type, e.g. "image/jpeg" or "image/webp".
        prompt: The full edit instruction (preserve-list, add-list,
            negative constraints — built by the caller from the
            virtual-staging skill's edit-prompt template).

    Returns:
        A dict with either:
          - {"image_base64": "...", "mime_type": "image/png"} on success
          - {"error": "..."} on failure
    """
    if not GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY is not configured on this server."}

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_base64,
                        }
                    },
                ],
            }
        ],
        # Ask Gemini to return image output.
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }

    try:
        resp = requests.post(
            GEMINI_ENDPOINT,
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=120,
        )
    except requests.RequestException as exc:
        return {"error": f"Request to Gemini failed: {exc}"}

    if resp.status_code != 200:
        return {"error": f"Gemini API error {resp.status_code}: {resp.text[:2000]}"}

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return {"error": f"No candidates returned by Gemini: {data}"}

    parts = candidates[0].get("content", {}).get("parts", [])
    for part in parts:
        # Google's JSON responses use camelCase; be defensive about casing.
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return {
                "image_base64": inline["data"],
                "mime_type": inline.get("mimeType") or inline.get("mime_type") or "image/png",
            }

    return {"error": f"No image data found in Gemini response: {data}"}


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "gemini_key_configured": bool(GEMINI_API_KEY)})


# --- Optional bearer-token auth on the MCP endpoint itself ---
# FastMCP's streamable-http app is a Starlette ASGI app; wrap it with a thin
# middleware that checks Authorization: Bearer <MCP_SHARED_SECRET> if one is
# configured, so the server isn't wide open to anyone with the URL.
if MCP_SHARED_SECRET:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.url.path == "/healthz":
                return await call_next(request)
            auth = request.headers.get("authorization", "")
            if auth != f"Bearer {MCP_SHARED_SECRET}":
                return PlainTextResponse("Unauthorized", status_code=401)
            return await call_next(request)

    mcp._mcp_server  # no-op touch, keeps import ordering obvious
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)
else:
    app = mcp.streamable_http_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
