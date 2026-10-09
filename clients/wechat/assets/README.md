# Court effects

Original synthesized mono 16-bit PCM at 22,050 Hz, created with Python math, seeded noise (seed 7), and wave. No external recordings.

- dribble.wav: 0.16 s, exponentially decaying 140-to-70 Hz tone and filtered impact noise.
- swish.wav: 0.30 s, short high-frequency noise decay.
- rim.wav: 0.36 s, decaying 480/1210 Hz resonances and an impact transient.
- buzzer.wav: 0.65 s, 196 Hz fundamental with harmonics.
- whistle.wav: existing project whistle, 0.75 s.

The player must tap Start or the sound switch before effects play. Dribble cues follow the held-ball bounce phase from the shared court, stop during passes/free throws/timeouts, and use the phone's media volume. tests/test_wechat_chinese.py measures the actual PCM files; tests/wechat_live.cjs checks real audio onPlay/error callbacks and the mute control.
