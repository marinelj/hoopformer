// Short, original PCM effects. A held ball uses the same bounce phase as core/court.js.
function eventSound(event) {
  if (event.kind === "shot" || event.kind === "free_throws") return event.value ? "swish" : "rim";
  if (event.kind === "foul" || event.kind === "period_start" || (event.kind === "timeout" && event.zone !== "coach")) return "whistle";
  if (event.kind === "period_end") return "buzzer";
  if (event.kind === "rebound" || event.kind === "block") return "dribble";
  return null;
}

function dribbleBeat(time, ball, playing, dead) {
  if (!playing || dead || !ball || ball.holder == null) return null;
  return Math.floor((time * 7 - Math.PI / 2) / Math.PI);
}

function createSound(onError) {
  const contexts = {}, stats = { played: {}, errors: [] };
  let enabled = false, destroyed = false;
  // Respect media volume, and provide an explicit in-game mute button.
  if (wx.setInnerAudioOption) wx.setInnerAudioOption({ obeyMuteSwitch: false, mixWithOther: true });
  for (const kind of ["dribble", "swish", "rim", "whistle", "buzzer"]) {
    const audio = wx.createInnerAudioContext({ useWebAudioImplement: true });
    audio.obeyMuteSwitch = false;
    audio.volume = kind === "dribble" ? 0.8 : 0.55;
    audio.onPlay(() => { stats.played[kind] = (stats.played[kind] || 0) + 1; });
    audio.onError((error) => {
      stats.errors.push({ kind, code: error.errCode });
      if (!destroyed && onError) onError("音效未能播放，点声音开关重试。");
    });
    audio.src = `/assets/${kind}.wav`;
    contexts[kind] = audio;
  }
  return {
    stats,
    enable(value) { enabled = !!value; if (!enabled) this.stop(); },
    play(kind) {
      if (!enabled || destroyed || !contexts[kind]) return false;
      contexts[kind].stop(); contexts[kind].play();
      return true;
    },
    stop() { for (const audio of Object.values(contexts)) audio.stop(); },
    destroy() { destroyed = true; enabled = false; for (const audio of Object.values(contexts)) audio.destroy(); },
  };
}

module.exports = { eventSound, dribbleBeat, createSound };
