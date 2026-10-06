// Where the game server is (`hoopformer serve` on your computer).
// - WeChat DevTools on the same computer: http://127.0.0.1:8000 works, because project.config.json turns off the
//   domain check (urlCheck: false, "Does not verify valid domain names" in the tools).
// - A phone (preview or real-device debugging): run `hoopformer serve --host 0.0.0.0`, put this computer's address
//   on your local network here (for example http://192.168.1.20:8000), keep the phone on the same network.
// - A released Mini Program can only call HTTPS domains added in its admin console.
module.exports = {
  SERVER: "http://127.0.0.1:8000",
  HOME: "",       // your team, by tricode ("": the server's default, the 1990s All-Stars)
  AWAY: "",       // the AI coach's team ("": the 2000s All-Stars)
  VOICE: false,   // hold-to-talk needs the WechatSI speech plugin (see clients/README.md); off: 🎙 and 🗯 open a text box
};
