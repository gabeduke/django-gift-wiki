# MCP server (`gift_mcp`)

Lets an AI assistant — Claude on the web, phone, Desktop or Claude Code — read the family's
lists and add items, **acting as the person who connected it**. It follows the same surprise
rules as the website because it calls the same code (`gift/services.py`).

Modelled on the FWP board server (`fwp-admin`: `lib/mcp-server.ts`, `lib/oauth.ts`) and
`grow-buddy`'s Django OAuth plan, trimmed to what this app needs.

## Turning it on

It ships **dark**. With the `MCP_ENABLED` feature flag off, `/mcp`, `/oauth/*`, `/connect-ai/` and
the `/.well-known/oauth-*` documents all return 404.

1. Merge and deploy. Migration `gift_mcp.0001_initial` only *creates* four tables and touches
   nothing existing; the Cloud Run migration job applies it before the service starts.
2. `/admin/` → **Feature flags** → add `MCP_ENABLED`, tick **enabled**. No restart needed.
3. Sanity check (no credentials needed):
   ```bash
   curl -s https://giftwiki.leetserve.com/.well-known/oauth-authorization-server
   curl -si -X POST https://giftwiki.leetserve.com/mcp   # 401 with a WWW-Authenticate header
   ```
4. Connect yourself first (below) and try it before telling the family.

Turning the flag off again disables everything immediately; existing tokens stay in the database
but can't be used.

## Connecting

**Claude on the web or phone (and Desktop):** Settings → Connectors → *Add custom connector* →
paste `https://giftwiki.leetserve.com/mcp`. You'll be sent to the Gift Wiki to sign in with
Google and approve. This is the OAuth path.

**Claude Code (or scripts):** open `/connect-ai/` (Profile → *AI assistant*), make a token, and:

```bash
claude mcp add --transport http gift-wiki https://giftwiki.leetserve.com/mcp \
  --header "Authorization: Bearer gwt_…"
```

The token is shown once and stored only as a hash.

## What it can do

| Tool | |
|---|---|
| `list_wishlists` | Every list, whose it is, how many items *you* can see, and whether you're `owner-side` or a `gift-giver` |
| `get_wishlist` | The items on one list, as you may see them |
| `search_items` | Find items by words, across all lists or one |
| `add_item` | Add an item. Refuses duplicates unless `allow_duplicate` |

Read + add only. There is deliberately **no** edit, delete or "mark purchased". A successful prompt
injection can therefore do no worse than add a junk item that someone removes with one tap.

### The spoiler rules (the part that matters)

Unchanged from the website — the tools call `gift/services.py` and add nothing of their own:

- **Surprise items** are hidden from a list's owner and from the person it is kept for. They are
  not even counted. A *manager* does see them, exactly as on the wishlist page.
- **Which items are bought** is never shown to anyone owner-side (owner, dependent, manager).
- **What you add:** owner-side → an ordinary item. Anyone else → automatically a surprise.
- `search_items(unpurchased_only=true)` is **ignored** on lists the person is owner-side of:
  filtering by purchase status would reveal which items were bought by what disappears.
- The duplicate check only looks at items the person may see, so "already on the list" can't
  reveal a surprise.

## Security model

- **Who you are comes from the token, never from an argument.** No tool has a `user` parameter;
  unknown arguments are rejected. There is no request a model can phrase that means "act as someone
  else" or "show me what's hidden from me".
- **Bearer tokens only on `/mcp`.** A signed-in browser tab can't be turned against it (no cookies,
  no CSRF surface). Tokens are 256 random bits, stored as SHA-256 hashes.
- **Allowlist re-checked on every request.** Remove someone (`AllowedEmail`, `DJANGO_ALLOWED_USERS`)
  or deactivate them and their personal tokens *and* OAuth connections stop working at once.
- **OAuth:** PKCE (S256) is mandatory; public clients only (no secrets); codes are single-use,
  5 minutes; access tokens 1 hour; refresh tokens 30 days and **rotate on use** — replaying a used
  code or refresh token revokes everything that app holds for that person.
- **Apps can't register a return address they don't own.** Registration only accepts `https` on
  `MCP_REDIRECT_HOSTS` (default `claude.ai`, `claude.com`, `chatgpt.com`) or `http` on localhost.
  Registration is capped (500) and unused registrations are swept after 30 days.
- **Consent is explicit.** `/oauth/authorize` requires the normal Google sign-in, names the app
  and where you'll land, and treats anything other than the Approve button as "no". It can't be
  framed (`X-Frame-Options: DENY`).
- **Gift secrets never reach the logs.** Tool calls log the tool name and user id — not arguments,
  results, or tokens. (A test fails if that changes.)

## Operating it

- **A person loses a device / wants out:** `/connect-ai/` → revoke the token or *Disconnect* the app.
- **Someone leaves the family:** remove them from the allowlist. Done.
- **See who has what:** `/admin/` → *AI assistant access (MCP)*. Read-mostly: nobody mints
  credentials from the admin; set `revoked_at` on a token to revoke it.
- **Neon compute hours:** token lookups happen only when a client is actually used, and `last used`
  is written at most once an hour per token. Nothing polls. Don't add a health probe against `/mcp`.
- **Logs:** look for `mcp.call` (tool, user_id, ok), `mcp.authorized`, `mcp.tool_error`.
- **Origin:** the OAuth documents advertise the request's own host. `giftwiki/wsgi.py` marks every
  request `https`, so production is right with no config. A client-sent `X-Forwarded-Proto` is
  deliberately ignored (the documents are cacheable). Locally over plain http, set
  `MCP_PUBLIC_ORIGIN=http://localhost:8000`.

## Design notes

- **No ASGI switch.** The server is stateless JSON-RPC over `POST` returning plain JSON — the
  simplest form of the Streamable HTTP transport. `GET`/`DELETE` return 405 (no server-push stream),
  which the official SDK client accepts. That's what FWP's board server does too, and it means
  `gunicorn giftwiki.wsgi:application` is untouched. (The in-app assistant spec assumed ASGI would
  be needed; it isn't, for tools-only MCP.)
- **Hand-rolled JSON-RPC** (`gift_mcp/server.py`, ~150 lines) rather than the `mcp` SDK, which needs
  ASGI. Verified against the official Python SDK client (v2.3.0) over real HTTP under gunicorn.
- **Shared rules extracted, not copied.** `gift/services.py` holds `can_add_openly`,
  `active_items_visible_to`, `person_display_name` and `create_item_for`; `gift/views.py` imports them,
  so the web app and MCP can't drift. The in-app assistant should reuse `gift_mcp/tools.py`
  (or move it) rather than write a second tool layer.
- **Why `gwt_`/`gwa_`/`gwr_` prefixes:** a pasted token is recognisable and a leaked one is greppable.

## Not built (yet)

- **Mark purchased / edit / delete tools.** Excluded on purpose for v1; "mark purchased" is the most
  useful next step (it's allowed to non-owner-side people only, so no spoiler risk) — add it as its
  own tool with the same `services` check.
- **Rate limiting** per person. Not needed for nine family members; revisit before opening wider.
- **Client ID Metadata Documents** (the newer alternative to dynamic registration). Not needed for
  Claude's connector today; FWP implements it if it becomes necessary.
- **`/oauth/revoke`** (RFC 7009). People revoke on `/connect-ai/` instead.

## Local development

```bash
MCP_ENABLED=TRUE MCP_PUBLIC_ORIGIN=http://localhost:8000 make run
```

Make a personal token on `/connect-ai/` (sign in as a user on the allowlist), then:

```bash
curl -s -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer gwt_…" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Tests: `tests/api/test_mcp_tools.py` (the spoiler matrix), `test_mcp_protocol.py`,
`test_mcp_oauth.py`, `test_mcp_connect.py`.
