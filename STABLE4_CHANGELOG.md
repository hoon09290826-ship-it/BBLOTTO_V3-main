# BBLOTTO V3 STABLE-4

- Removed the capture-phase click interception from `ui-stable.js`.
- Restored `app.js` as the single owner of button/menu events.
- Kept only DOM cleanup and global error logging in the fallback script.
- Added no-cache response headers for CSS and JavaScript assets.
- Added `/api/ui-health` for deployed-version verification.
- Updated visible version to `STABLE-4 · EVENT CONSOLIDATION`.
