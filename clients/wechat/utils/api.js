// The game server's API (src/hoopformer/game/server.py), the same one the web page uses.
const { SERVER } = require("../config.js");

function request(path, body) {   // GET without a body, POST with one; resolves with the JSON answer
  return new Promise((resolve, reject) => {
    wx.request({
      url: SERVER + path,
      method: body === undefined ? "GET" : "POST",
      data: body,
      header: { "content-type": "application/json" },
      success: (res) => (res.statusCode === 200 ? resolve(res.data) : reject(new Error((res.data && res.data.error) || `HTTP ${res.statusCode}`))),
      fail: (err) => reject(new Error(err.errMsg || "no connection to the game server")),
    });
  });
}

module.exports = { request };
