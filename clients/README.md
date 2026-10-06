# Clients: the two ways to coach a game

Both interfaces play the same game. The engine, the players' numbers, the levers and the coach's rules run once, in
Python, behind `hoopformer serve` (`src/hoopformer/game/server.py`). Each client draws the court and sends the
coach's choices to that server.

```
clients/
  core/court.js     the court's rules, shared by both clients: where every player is at every moment of a possession,
                    the tactics (set plays, defenses, roles, who fits each role), how each archetype moves, the calls
  web/              the browser page (production by default; debug: `hoopformer serve --debug` or ?debug=1)
  wechat/           the WeChat Mini Program (it keeps a copy of core/court.js: `hoopformer clients` updates it)
```

- **The engine decides what happens** (who shoots, from where, whether it goes in). `court.js` decides where everyone is
  while it happens, from the engine's events and the coach's tactic, so both clients show the same game the same way.
- **The server's API** is the same for both: `GET /api/new` (a game as data; the web page gets it embedded at `GET /`),
  `GET /api/next` (the next possession), `POST /api/call`, `/api/tactics`, `/api/timeout`, `/api/trash`, `/api/say`.
- **The web page** is assembled by the server: `web/courtside.html` with `core/court.js` inlined, so it stands alone.

## The web page

`uv run hoopformer serve`, then open the address it prints. That's the production page. For the debug page, with
the engine's numbers and the explanations, use `--debug` or add `?debug=1` to the page address.

## The WeChat Mini Program

The layout is compact and turns with the phone:
- **Portrait:** a slim scoreboard, the court the full width of the screen, a strip with the tactic in play, the
  Timeout button, and two tabs (Coach, Play-by-play).
- **Landscape:** the court fills the left side under the scoreboard; the Timeout button and the tabs are a column on
  the right.

The coaching is the same as on the web:
- the tactic and each player's role, changed only in a timeout;
- a call for each player or the whole team;
- 🎙 to talk to a player, 🗯 to talk trash to his man;
- 15 timeouts, each with a whistle.

Tap a player on the court for his name and archetype.

1. Start the server: `uv run hoopformer serve --port 8000`.
2. Install WeChat DevTools and import the folder `clients/wechat`. The project uses the test AppID (`touristappid`);
   use your own Mini Program's AppID to preview on a phone.
3. In DevTools the game connects to `http://127.0.0.1:8000` (`config.js`). The domain check is off in
   `project.config.json`.
4. On a phone (preview or real-device debugging):
   - start the server with `uv run hoopformer serve --port 8000 --host 0.0.0.0`;
   - set `SERVER` in `config.js` to this computer's address on your local network (for example `http://192.168.1.20:8000`);
   - keep the phone on the same network.

   A released Mini Program can only call an HTTPS domain registered in its admin console, so the server must then run
   behind one.
5. **Voice:**
   - Without the speech plugin (the default), 🎙 and 🗯 open a text box.
   - To speak instead, add the WechatSI plugin to `app.json`:
     `"plugins": { "WechatSI": { "version": "0.3.5", "provider": "wx069ba97219f66d99" } }`. Then add the plugin to your
     Mini Program in its admin console and set `VOICE: true` in `config.js`.

After changing `core/court.js`, run `uv run hoopformer clients` to update the Mini Program's copy (a Mini Program can
only load its own files). `tests/test_clients.py` fails until the copy matches.
