# Experiments

The project's lab notebook. Add one line per run, newest last. Never edit old lines: a wrong result stays, and a later line corrects it.

| Date | Who | Machine | Git | What | Result |
|---|---|---|---|---|---|
| 2026-09-29 | Claude | MacBook Air M5 | f29886f | M1 matmul 4096×4096, float32 | CPU 1.96 TFLOPS, GPU (mps) 2.74 TFLOPS, GPU 1.4× faster |
| 2026-09-29 | marinelj | Mac Studio | c738a14 | `hoopformer baselines`, validation 2024-25 (246,541 possessions) | B0 shares 1.12005; B1 situation 1.11452 (+5.54 mnats); **B2 linear lineup 1.11152 (+8.53 mnats), the bar**. B2 strength search: C=1e-4 1.11369, 1e-3 1.11152 (best, not on an edge), 1e-2 1.11196, 1e-1 1.11368 |
