// The game server's API (src/hoopformer/game/server.py), the same one the web page uses.
const config = require("../config.js");
let cloudReady = false;
let pending = Promise.resolve();
let gameId = "";

function sendRequest(path, body) {
  return new Promise((resolve, reject) => {
    const isNew = path.split("?")[0] === "/api/new";
    if (!isNew && gameId && !/[?&]game_id=/.test(path)) path += `${path.includes("?") ? "&" : "?"}game_id=${encodeURIComponent(gameId)}`;
    let finished = false;
    const waitMs = path.split("?")[0] === "/api/say" ? 135000 : 15000;
    const timer = setTimeout(() => { finished = true; reject(new Error("比赛服务响应超时，请稍后重试。")); }, waitMs);
    const options = {
      method: body === undefined ? "GET" : "POST",
      timeout: waitMs,
      data: body,
      header: { "content-type": "application/json" },
      success: (res) => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        let data = res.data;
        if (typeof data === "string") { try { data = JSON.parse(data); } catch (_) { /* non-JSON error page */ } }
        if (res.statusCode === 200 && data && typeof data === "object") {
          if (isNew) gameId = data.game_id || "";
          return resolve(data);
        }
        const message = res.statusCode === 404
          ? "云服务已连接，但没有比赛接口。请上传 Hoopformer 后端代码并使用端口 8000（HTTP 404）。"
          : (data && data.error) || `比赛服务返回 HTTP ${res.statusCode}`;
        const error = new Error(message);
        error.status = res.statusCode; error.code = data && data.code;
        reject(error);
      },
      fail: (err) => { if (finished) return; finished = true; clearTimeout(timer); reject(new Error(err.errMsg || "连接比赛服务失败，请检查网络后重试。")); },
    };
    if (config.CLOUD_ENV && config.CLOUD_SERVICE) {
      if (!cloudReady) {
        wx.cloud.init({ env: config.CLOUD_ENV });
        cloudReady = true;
      }
      options.header["X-WX-SERVICE"] = config.CLOUD_SERVICE;
      wx.cloud.callContainer({ ...options, config: { env: config.CLOUD_ENV }, path });
    } else {
      wx.request({ ...options, url: config.SERVER + path });
    }
  });
}

function request(path, body) {
  // Deliver game steps and coaching responses in the order the player requested them.
  const result = pending.then(() => sendRequest(path, body));
  pending = result.catch(() => {});
  return result;
}

module.exports = { request };
