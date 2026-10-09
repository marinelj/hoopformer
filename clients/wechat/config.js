// CLOUD_ENV/CLOUD_SERVICE 使用微信云托管。清空这两项才使用下方 SERVER 进行本地调试。
// Where the local game server is (`hoopformer serve` on your computer).
// - WeChat DevTools on the same computer: http://127.0.0.1:8000 works, because project.config.json turns off the
//   domain check (urlCheck: false, "Does not verify valid domain names" in the tools).
// - A phone (preview or real-device debugging): run `hoopformer serve --host 0.0.0.0`, put this computer's address
//   on your local network here (for example http://192.168.1.20:8000), keep the phone on the same network.
// - A released Mini Program can only call HTTPS domains added in its admin console.
module.exports = {
  CLOUD_ENV: "prod-d2gq2p7vs296b0a1e", // 用户创建的微信云托管环境。
  CLOUD_SERVICE: "flask-y3ue",         // 实际服务名；模板创建后无需改名。
  SERVER: "http://127.0.0.1:8000",
  HOME: "",       // your team, by tricode ("": the server's default, the 1990s All-Stars)
  AWAY: "",       // the AI coach's team ("": the 2000s All-Stars)
  VOICE: true,    // Use Chinese WechatSI when registered; otherwise keep text coaching available.
};
