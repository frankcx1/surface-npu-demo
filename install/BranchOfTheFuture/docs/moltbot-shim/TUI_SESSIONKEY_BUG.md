# Bug: TUI silently drops all chat events due to case-sensitive sessionKey comparison

**Repo:** badlogic/pi-mono (OpenClaw)
**Component:** `dist/tui/tui-event-handlers.js`
**Severity:** High — responses appear blank; no error shown

---

## Summary

The TUI's chat event handler uses a strict equality check (`!==`) to compare the incoming event's `sessionKey` against the TUI's stored session key. However, the gateway normalizes session keys to lowercase during session resolution (via `resolveSessionKey()` in `config/sessions/session-key.js:23`), while the TUI preserves the original mixed-case session name from the user. This case mismatch causes **every chat event to be silently dropped**, making the TUI appear blank even though the gateway is sending correct responses.

## Reproduction

1. Start the gateway: `npx openclaw gateway`
2. Start the TUI: `npx openclaw tui`
3. Create or use a session with mixed-case characters in the name (e.g. `Surface-Laptop-7-Phi`)
4. Send any message
5. **Expected:** Response appears in TUI
6. **Actual:** TUI shows blank — no response rendered, no error shown, status returns to "idle"

Session names derived from Windows hostnames commonly have mixed case (e.g. `Surface-Laptop-7`), making this easy to hit on Windows machines.

## Root Cause

Two code paths handle session keys differently:

**Gateway side** — `config/sessions/session-key.js:23`:
```javascript
export function resolveSessionKey(scope, ctx, mainKey) {
    const explicit = ctx.SessionKey?.trim();
    if (explicit) {
        return explicit.toLowerCase();  // ← lowercases the key
    }
    ...
}
```

**TUI side** — `tui/tui-event-handlers.js:55`:
```javascript
if (evt.sessionKey !== state.currentSessionKey) {
    return;  // ← case-sensitive comparison, silently drops
}
```

The gateway broadcasts chat events with `sessionKey: "agent:main:surface-laptop-7-phi"` (lowercase), but the TUI stores `"agent:main:Surface-Laptop-7-Phi"` (original case). The strict `!==` comparison fails, and the event is silently dropped with no logging.

## Impact

- **100% blank responses** when the session name contains uppercase characters
- No error is shown — the TUI just shows "idle" as if nothing happened
- Gateway logs show the response was generated and sent correctly
- Extremely difficult to diagnose since the failure is silent and the server side is working perfectly
- Common on Windows where machine names have mixed case (Surface-Laptop-7, DESKTOP-ABC, etc.)

## Fix

One-line change — make the comparison case-insensitive:

```diff
-        if (evt.sessionKey !== state.currentSessionKey) {
+        if (evt.sessionKey?.toLowerCase() !== state.currentSessionKey?.toLowerCase()) {
             return;
         }
```

**File:** `dist/tui/tui-event-handlers.js` (line 55)

Alternatively, the gateway could preserve the original case in `resolveSessionKey()`, but that would be a larger change with potential side effects on session store lookups.

## Patch

See `tui-sessionkey-case-fix.patch` for the complete diff.
