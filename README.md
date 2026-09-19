# Gemini Image Staging — MCP Server

A tiny remote MCP server with one tool, `stage_image`, that sends a room
photo + an editing prompt to Google's Gemini image model and returns the
staged version. Built to plug into Claude's `virtual-staging` skill as a
custom connector.

Tested locally in this environment (starts cleanly, `/healthz` returns
`{"status":"ok",...}`). **Not yet tested against the real Gemini API** —
this sandbox's network policy blocks outbound calls to
`generativelanguage.googleapis.com`, so that call has to be verified once
the server is actually deployed somewhere with normal internet access.

## Files
- `server.py` — the server itself (Python, uses the official `mcp` SDK's
  streamable-HTTP transport)
- `requirements.txt` — Python dependencies
- `Dockerfile` — so any container host (Cloud Run, Render, Railway, Fly.io)
  can build and run it the same way
- `.env.example` — the environment variables it needs (copy to `.env` for
  local testing only — never commit a real `.env`)

## Environment variables
| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | yes | Your key from https://aistudio.google.com/apikey |
| `MCP_SHARED_SECRET` | strongly recommended | A random string you pick. If set, every request must send `Authorization: Bearer <that string>`. Without it, anyone with the URL can call your Gemini key. |
| `PORT` | no (defaults to 8080) | Some hosts (Cloud Run, Render) set this automatically |
| `GEMINI_MODEL` | no (defaults to `gemini-2.5-flash-image`) | Override if Google renames/versions the model |

## Run it locally
```bash
pip install -r requirements.txt
export GEMINI_API_KEY=your-real-key
export MCP_SHARED_SECRET=$(openssl rand -hex 24)
python3 server.py
# -> serves http://0.0.0.0:8080/mcp (the MCP endpoint)
#    and    http://0.0.0.0:8080/healthz (plain health check, no auth)
```

## Deploy it (pick one)

### Option A — Render (simplest, has a free tier)
1. Push this folder to a GitHub repo.
2. In Render: New -> Web Service -> connect the repo.
3. Render will detect the `Dockerfile` automatically (or set the runtime
   to Docker manually if asked).
4. Under Environment, add `GEMINI_API_KEY` and `MCP_SHARED_SECRET` as
   secrets.
5. Deploy. Render gives you a URL like `https://your-service.onrender.com`.
   The MCP endpoint is `https://your-service.onrender.com/mcp`.

### Option B — Google Cloud Run
```bash
gcloud run deploy gemini-image-staging \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=your-real-key,MCP_SHARED_SECRET=your-random-string
```
Cloud Run prints an HTTPS URL when it finishes — the MCP endpoint is
`<that-url>/mcp`.

### Option C — Railway / Fly.io
Both auto-detect the `Dockerfile`. Push the repo, set the two env vars in
their dashboard/CLI, deploy, and use the HTTPS URL they hand you the same
way.

## Add it to Claude
1. claude.ai -> Settings -> Connectors -> Add custom connector.
2. URL: `https://<your-deployed-host>/mcp`
3. Auth: if you set `MCP_SHARED_SECRET`, add a header
   `Authorization: Bearer <that string>` in the connector's auth config
   (custom connectors support a static header/bearer token).
4. Save, then enable the connector for the chat/project where you want to
   run virtual staging.
5. Ask Claude to virtually stage a photo — the `virtual-staging` skill
   already looks for an available image-editing tool and will find
   `stage_image` automatically.

## Security notes
- Treat `GEMINI_API_KEY` and `MCP_SHARED_SECRET` as secrets: environment
  variables/host secrets only, never in a git commit or chat message.
- `MCP_SHARED_SECRET` is a simple shared-secret gate, not full OAuth — fine
  for a personal tool, but rotate it if the URL ever leaks.
- The server has no rate limiting — Gemini API usage on your key is billed
  to your Google account, so don't share the deployed URL/secret publicly.
