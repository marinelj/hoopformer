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
