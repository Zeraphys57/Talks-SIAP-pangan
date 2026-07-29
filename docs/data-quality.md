# Data quality report

**Generated** by `siap preprocess --report`. Do not edit by hand — it is
rebuilt from `price_daily_unified` and will be overwritten.

Generated 2026-07-29 10:23 UTC, covering 2023-07-28 to 2026-07-29.

## Overall

| metric | value |
|---|---:|
| daily rows | 50,004 |
| observed | 39,137 (78.3%) |
| imputed | 10,239 (20.5%) |
| still missing | 628 (1.3%) |

Imputation is linear and capped at three consecutive days. Longer gaps
stay NULL. Every imputed row is flagged `is_imputed` and is excluded from
ground-truth evaluation in M7.

## Contributing sources

| source | observations | first | last |
|---|---:|---|---|
| `jogja` | 12 | 2026-07-28 | 2026-07-28 |
| `pihps` | 28,116 | 2023-07-31 | 2026-07-28 |
| `siskaperbapo` | 13,176 | 2023-07-28 | 2026-07-29 |
| `sp2kp` | 26,909 | 2024-03-01 | 2026-07-28 |

## Completeness per commodity x region

| region | commodity | days | observed | imputed | missing | avg sources | complete |
|---|---|---:|---:|---:|---:|---:|---:|
| di_yogyakarta | beras-medium | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | beras-premium | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | cabai-merah-keriting | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | cabai-rawit-merah | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | bawang-merah | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | bawang-putih | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | telur-ayam-ras | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | daging-ayam-ras | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | daging-sapi | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | minyak-goreng-curah | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | minyak-goreng-kemasan | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| di_yogyakarta | gula-pasir | 1,094 | 781 | 309 | 4 | 1.21 | 99.6% |
| jawa_tengah | beras-medium | 1,094 | 789 | 305 | 0 | 1.23 | 100.0% |
| jawa_tengah | beras-premium | 1,094 | 789 | 305 | 0 | 1.22 | 100.0% |
| jawa_tengah | cabai-merah-keriting | 1,094 | 789 | 305 | 0 | 1.22 | 100.0% |
| jawa_tengah | cabai-rawit-merah | 1,094 | 789 | 305 | 0 | 1.23 | 100.0% |
| jawa_tengah | bawang-merah | 1,094 | 789 | 305 | 0 | 1.22 | 100.0% |
| jawa_tengah | bawang-putih | 1,094 | 789 | 305 | 0 | 1.22 | 100.0% |
| jawa_tengah | telur-ayam-ras | 1,094 | 789 | 305 | 0 | 1.22 | 100.0% |
| jawa_tengah | daging-ayam-ras | 1,094 | 789 | 305 | 0 | 1.22 | 100.0% |
| jawa_tengah | daging-sapi | 1,094 | 789 | 305 | 0 | 1.22 | 100.0% |
| jawa_tengah | minyak-goreng-curah | 1,094 | 789 | 305 | 0 | 1.22 | 100.0% |
| jawa_tengah | minyak-goreng-kemasan | 1,094 | 789 | 305 | 0 | 1.22 | 100.0% |
| jawa_tengah | gula-pasir | 1,094 | 789 | 305 | 0 | 1.22 | 100.0% |
| jawa_timur | beras-medium | 1,098 | 1,098 | 0 | 0 | 2.22 | 100.0% |
| jawa_timur | beras-premium | 1,098 | 1,098 | 0 | 0 | 2.21 | 100.0% |
| jawa_timur | cabai-merah-keriting | 1,098 | 1,098 | 0 | 0 | 2.21 | 100.0% |
| jawa_timur | cabai-rawit-merah | 1,098 | 1,098 | 0 | 0 | 2.22 | 100.0% |
| jawa_timur | bawang-merah | 1,098 | 1,098 | 0 | 0 | 2.21 | 100.0% |
| jawa_timur | bawang-putih | 1,098 | 1,098 | 0 | 0 | 2.21 | 100.0% |
| jawa_timur | telur-ayam-ras | 1,098 | 1,098 | 0 | 0 | 2.21 | 100.0% |
| jawa_timur | daging-ayam-ras | 1,098 | 1,098 | 0 | 0 | 2.21 | 100.0% |
| jawa_timur | daging-sapi | 1,098 | 1,098 | 0 | 0 | 2.21 | 100.0% |
| jawa_timur | minyak-goreng-curah | 1,098 | 1,098 | 0 | 0 | 2.21 | 100.0% |
| jawa_timur | minyak-goreng-kemasan | 1,098 | 1,098 | 0 | 0 | 2.22 | 100.0% |
| jawa_timur | gula-pasir | 1,098 | 1,098 | 0 | 0 | 2.21 | 100.0% |
| kota_yogyakarta | beras-medium | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | beras-premium | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | cabai-merah-keriting | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | cabai-rawit-merah | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | bawang-merah | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | bawang-putih | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | telur-ayam-ras | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | daging-ayam-ras | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | daging-sapi | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | minyak-goreng-curah | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | minyak-goreng-kemasan | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| kota_yogyakarta | gula-pasir | 1 | 1 | 0 | 0 | 1.00 | 100.0% |
| nasional | beras-medium | 880 | 591 | 241 | 48 | 0.67 | 94.5% |
| nasional | beras-premium | 880 | 593 | 239 | 48 | 0.67 | 94.5% |
| nasional | cabai-merah-keriting | 880 | 592 | 240 | 48 | 0.67 | 94.5% |
| nasional | cabai-rawit-merah | 880 | 591 | 237 | 52 | 0.67 | 94.1% |
| nasional | bawang-merah | 880 | 593 | 239 | 48 | 0.67 | 94.5% |
| nasional | bawang-putih | 880 | 593 | 239 | 48 | 0.67 | 94.5% |
| nasional | telur-ayam-ras | 880 | 593 | 239 | 48 | 0.67 | 94.5% |
| nasional | daging-ayam-ras | 880 | 593 | 239 | 48 | 0.67 | 94.5% |
| nasional | daging-sapi | 880 | 592 | 240 | 48 | 0.67 | 94.5% |
| nasional | minyak-goreng-curah | 880 | 593 | 239 | 48 | 0.67 | 94.5% |
| nasional | minyak-goreng-kemasan | 880 | 592 | 240 | 48 | 0.67 | 94.5% |
| nasional | gula-pasir | 880 | 593 | 239 | 48 | 0.67 | 94.5% |

## Largest cross-source disagreements

A spread of a factor of ten is a unit-conversion bug, not a market. These
are the widest observed, for inspection at the M2 gate.

| region | commodity | date | min | max | sources | spread |
|---|---|---|---:|---:|---:|---:|
| jawa_tengah | cabai-merah-keriting | 2024-04-10 | 36,650 | 60,000 | 2 | 48.3% |
| di_yogyakarta | cabai-merah-keriting | 2024-09-10 | 17,700 | 28,750 | 2 | 47.6% |
| di_yogyakarta | cabai-merah-keriting | 2024-09-09 | 17,800 | 28,750 | 2 | 47.0% |
| di_yogyakarta | cabai-rawit-merah | 2024-04-15 | 24,000 | 37,500 | 2 | 43.9% |
| jawa_tengah | cabai-merah-keriting | 2024-04-11 | 36,650 | 56,667 | 2 | 42.9% |
| di_yogyakarta | cabai-merah-keriting | 2024-09-11 | 17,200 | 26,250 | 2 | 41.7% |
| jawa_tengah | cabai-rawit-merah | 2024-04-10 | 35,000 | 52,500 | 2 | 40.0% |
| di_yogyakarta | cabai-merah-keriting | 2024-11-15 | 15,133 | 22,500 | 2 | 39.1% |
| di_yogyakarta | cabai-merah-keriting | 2024-09-12 | 16,850 | 25,000 | 2 | 38.9% |
| di_yogyakarta | cabai-merah-keriting | 2024-09-13 | 17,000 | 25,000 | 2 | 38.1% |
| di_yogyakarta | cabai-merah-keriting | 2024-11-26 | 14,150 | 20,750 | 2 | 37.8% |
| di_yogyakarta | cabai-merah-keriting | 2024-11-11 | 15,750 | 22,500 | 2 | 35.3% |
| jawa_timur | cabai-rawit-merah | 2025-12-02 | 51,761 | 71,800 | 3 | 35.3% |
| jawa_timur | bawang-merah | 2024-04-16 | 38,754 | 54,200 | 3 | 35.1% |
| jawa_timur | bawang-merah | 2024-04-10 | 26,000 | 39,250 | 3 | 34.8% |
