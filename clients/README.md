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

1. 当前使用微信云托管：`config.js` 的环境是 `prod-d2gq2p7vs296b0a1e`，服务名是 `flask-y3ue`，通过 `wx.cloud.callContainer` 连接。须在该服务发布 Hoopformer 后端，Dockerfile 为 `Dockerfile.cloudbase`，监听端口为 `8000`。2026-10-09 已实际验证云端比赛接口；后续后端修复仍须重新发布部署分支。
2. Install WeChat DevTools and import the folder `clients/wechat`. The project AppID is `wxc261b766e2ee99f3`.
3. 本地调试时清空 `CLOUD_ENV` 和 `CLOUD_SERVICE`，启动 `uv run hoopformer serve --port 8000`，然后 `SERVER` 才会生效。`http://127.0.0.1:8000` 适用于同一电脑的开发者工具。
4. 使用本地服务进行真机调试时：
   - start the server with `uv run hoopformer serve --port 8000 --host 0.0.0.0`;
   - set `SERVER` in `config.js` to this computer's address on your local network (for example `http://192.168.1.20:8000`);
   - keep the phone on the same network.

   云托管内部调用无需配置公网域名；若改用普通 `wx.request`，发布版需要注册 HTTPS 合法域名。
5. **中文界面和语音：**
   - 记分牌、战术、球员任务、指令和比赛解说使用简单中文。比赛前或暂停时能改战术；临场指令、打字和喊话一直可用。
   - 每张卡片直接提供输入框：短按左侧发给队员，短按右侧发给对手；长按两侧按钮说普通话，松开后直接发送，上滑取消。没有确认子面板。可以对全队或某名球员下指令。
   - 语音使用微信同声传译 WechatSI。`config.js` 默认尝试启用；插件不可用时，会明确显示“语音尚未接入”，保留文字输入，不把打字当成录音。
   - **当前部署目标：**`project.config.json` 已配置 `wxc261b766e2ee99f3`，`app.json` 已加入 WechatSI。开发者工具须登录有该小程序权限的微信账号，并在该小程序后台的“设置 → 第三方服务 → 插件管理”添加微信同声传译。`app.voice.example.json` 保留完整的语音配置供核对。测试号 `touristappid` 不能代替正式账号上传或接入插件。
   - 首次录音需要麦克风权限。拒绝权限、没听清、识别失败或超时都会显示中文提示；也可以直接打字。语音会交给微信同声传译服务识别，松开后把文字发送给比赛服务。录音最长 30 秒。
   - 常用中文说法（如“打快一点”“加快节奏”“多传球”）会优先匹配当前可用的现有指令；其他话明确交给千问，云端缺失配置或调用失败会说明原因并保留输入。

上传前确认 `config.js` 的云环境/服务名及后端已运行；使用本地连接时再检查 `SERVER`。语音插件加载和上传都依赖有效的开发者登录，`INVALID_LOGIN, access_token expired` 表示应重新扫码登录。

After changing `core/court.js`, run `uv run hoopformer clients` to update the Mini Program's copy (a Mini Program can
only load its own files). `tests/test_clients.py` fails until the copy matches.

## 真机问题回归（2026-10-09）

临场指令按球员 id 发送，选择后五张卡片仍保留。比赛失效时可点“重新开赛”；战术或任务发送失败会回到原选择。运球、进球、打铁、哨声和节末蜂鸣跟随真实持球/比赛事件，暂停和传球时停止运球声。使用手机媒体音量；声音开关已删除，录音时暂时停止音效以免干扰识别。

每个客户端保留自己的 game_id，电脑开赛不会替换手机的比赛。当前会话保存在单实例内存中，最多 32 局、空闲两小时后失效；重启会丢失，仍不支持多实例路由。

真实开发者工具检查（不模拟 wx API）：
```sh
HOOPFORMER_AUTOMATOR=/path/to/miniprogram-automator node tests/wechat_live.cjs http://127.0.0.1:8128
```
先在 8128 启动实际服务器。脚本只临时改变模拟器内存中的地址，结束后恢复配置；不改配置文件。会实际打开新比赛、改变战术、发送指令和测试过期恢复。麦克风识别和手机扬声器听感须在手机实测。

## 紧凑界面与千问（2026-10-09）

继续比赛/叫暂停放在场地内，暂停次数只显示在按钮中。战术卡片随整页自然下滑，不使用固定高度或内部滚动条。左右发送按钮短按发送文字，长按录音、松开发送、上滑取消；发送失败保留输入。

预设指令直接调用比赛引擎。其他自由语言明确请求千问；未配置密钥、格式错误或调用失败会给出原因，不再把规则兜底当作千问成功。旧后端返回 rules 时客户端也会提示重新发布后端。

本地服务启动会读取根目录 Git 忽略的 `.env` 中的 `DASHSCOPE_API_KEY`。小程序不读取这个文件，Docker 构建也不打包它：云端须在 flask-y3ue 环境变量中配置有效密钥，并发布新版部署分支。当前本地值含非 ASCII 字符，尚未验证成功模型调用；只需在本地文件中替换为控制台完整 API Key，不要把值写进代码或提交。
