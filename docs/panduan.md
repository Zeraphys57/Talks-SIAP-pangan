# Panduan operasional SIAP-PANGAN

Panduan untuk orang yang **menjalankan dan mempertanggungjawabkan** sistem ini,
bukan untuk yang membacanya sebagai kode. Isinya: apa yang dikerjakan setiap
langkah, urutannya dan kenapa urutan itu penting, cara Grace dan Roy mengakses
`/lab`, serta batas-batas sistem yang perlu kamu tahu sebelum ditanya orang lain.

Dokumen lain: [architecture](architecture.md) untuk desain, [methods](methods.md)
untuk metode statistiknya, [deployment](deployment.md) untuk hosting,
[labelling](labelling.md) untuk protokol pelabelan, [changelog](changelog.md)
untuk setiap penyimpangan dari proposal awal beserta alasannya.

---

## 1. Apa yang sistem ini lakukan

Mengumpulkan harga komoditas pangan dari empat portal resmi Indonesia plus satu
sinyal permintaan dari Google Trends, mendeteksi anomali, mengelompokkan kondisi
harga, membedah pola musiman, lalu meleburnya jadi **satu tingkat peringatan per
komoditas** yang ditampilkan sebagai dashboard untuk pelaku UMKM.

> **Batas ruang lingkup.** Sistem ini deskriptif dan diagnostik. Dia mendeteksi
> anomali yang **sudah terjadi**, mengklasifikasi kondisi saat ini, dan
> memunculkan pola historis yang berulang. **Dia tidak meramal harga.**

Kalau ada yang bertanya "besok harga naik atau turun?", jawabannya: sistem ini
tidak menjawab pertanyaan itu, dan itu keputusan desain, bukan keterbatasan yang
belum dikerjakan.

## 2. Peta sistem: tiga bagian, tiga tempat

| Bagian | Isinya | Jalan di mana |
|---|---|---|
| `engine/` | Python: scraper, preprocessing, model, evaluasi | Laptopmu, dan GitHub Actions |
| Supabase | Postgres: satu-satunya tempat data tinggal | Cloud Supabase |
| `web/` | Next.js: dashboard publik + konsol `/lab` | Vercel |

Yang penting dipahami: **engine tidak di-host.** Dia dijalankan — olehmu secara
manual, atau oleh GitHub Actions sesuai jadwal. Yang di-host hanya `web/`, dan
web hanya bisa **membaca**. Semua penulisan data terjadi dari engine.

Alamat produksi:

- Dashboard: <https://talks-siap-pangan.vercel.app>
- Konsol pelabelan: <https://talks-siap-pangan.vercel.app/lab>
- Kuesioner SUS: <https://talks-siap-pangan.vercel.app/lab/sus>

## 3. Alur data, langkah demi langkah

Urutannya bukan selera. Setiap langkah membaca hasil langkah sebelumnya.

```
ingest / backfill / trends     ambil data mentah dari portal
          ↓
preprocess                     satukan sumber jadi satu seri harian
          ↓
analyze          cluster          seasonal
(anomali)        (rezim)          (musiman)
          ↓         ↓                ↓
                 fuse              satu tingkat peringatan per komoditas
                   ↓
              dashboard
```

### 3.1 Pengumpulan data

**`siap ingest`** — mengambil **satu hari** dari semua sumber aktif dan menyimpan
harga per-sumber beserta salinan mentah halamannya.

Dia sengaja mengambil **hari kemarin**, bukan hari ini. Beberapa portal
memverifikasi dan menerbitkan angka pada sore hari; meminta tanggal yang belum
selesai mereka laporkan menghasilkan hari yang tipis dan **terlihat seperti
peristiwa pasar** padahal hanya data yang belum lengkap.

**`siap backfill`** — mengisi rentang tanggal ke belakang. Bisa dilanjut kalau
terputus di tengah, jadi tidak perlu mulai dari nol.

**`siap trends`** — sinyal permintaan dari Google Trends. Sifatnya *best-effort*:
pytrends membungkus endpoint yang tidak berdokumen dan dibatasi rate. Kalau
gagal, run tidak digagalkan — suku D pada peleburan turun ke 0 dengan alasan yang
dicatat.

**`siap coverage`** — tabel cakupan plus contoh provenance. Dipakai untuk
menjawab "angka ini dari mana": setiap harga bisa dilacak ke tanggal, ke halaman
asal, dan ke waktu pengambilannya.

**Prinsip yang tidak boleh dilanggar: tidak ada data fabrikasi.** Kalau scraper
gagal, run gagal dengan keras dan menulis baris `fetch_failures`. Tidak pernah
ada angka tebakan yang disisipkan supaya grafik terlihat penuh.

### 3.2 Penyatuan

**`siap preprocess`** — membangun ulang `price_daily_unified` dari harga
per-sumber.

Ini langkah yang paling sering disalahpahami, jadi perlu dijelaskan. Empat portal
melaporkan angka yang **berbeda untuk komoditas dan hari yang sama** — beda
metodologi, beda pasar sampel. Menggabungkannya mentah-mentah akan menghasilkan
lonjakan palsu setiap kali jumlah sumber yang melapor berubah. Jadi sumber-sumber
itu **ditautkan ke level yang sama dulu** sebelum direkonsiliasi.

Perlu diingat: `preprocess` melakukan **truncate dan tulis ulang**. Karena itu dia
tidak boleh dijalankan di atas ingest yang gagal — lihat §5.

### 3.3 Analisis

**`siap analyze`** — dua metode berjalan berdampingan, bukan salah satu:

- **Z-Score** — statistik, menandai harga yang jauh dari rata-rata 30 harinya
- **Isolation Forest** — machine learning, menandai pola yang tidak biasa

Keduanya dilaporkan terpisah supaya bisa dibandingkan di paper. Ada penjaga
*stale-baseline*: kalau baseline-nya sudah kedaluwarsa, dia menolak, bukan
menghitung dengan dasar usang.

**`siap cluster`** — K-Means pada tingkat komoditas × wilayah × bulan, mengelompokkan
kondisi harga jadi rezim ("cenderung stabil", dst). Nilai k dipaksa minimal 3 supaya
keluaran tiga zona yang dijanjikan brief benar-benar bisa tercapai.

**`siap seasonal`** — dekomposisi STL, memunculkan minggu-minggu yang secara
historis harganya di atas kebiasaan tahunan komoditas itu. Ada penjaga cakupan:
seri dengan riwayat terlalu pendek tidak dipaksa menghasilkan pola musiman.

**`siap fuse`** — melebur ketiganya jadi satu tingkat peringatan per komoditas:
**tenang → waspada → siaga**. Ada **gerbang koroborasi**: satu sinyal sendirian
tidak cukup menaikkan peringatan ke tingkat tertinggi. Ini yang mencegah satu
metode yang sedang gaduh membuat seluruh dashboard berstatus siaga.

Ada tingkat keempat, **`belum dapat dinilai`**, yang berada di luar urutan itu.
Artinya tidak ada detektor yang bisa memberi skor untuk tanggal tersebut. Dulu
kasus ini jatuh ke tingkat terendah dan terbaca "tidak ada yang aneh" — padahal
yang benar adalah "belum diperiksa". Dua hal itu berbeda, dan sekarang ditulis
berbeda.

Perhatikan bahwa tingkat peringatan **sengaja tidak memakai kata merah/kuning/
hijau**. Kata-kata itu dipakai oleh *zona* K-Means (`siap cluster`), yang
merupakan besaran lain — zona dihitung per bulan, peringatan per hari, dan
keduanya tampil di halaman yang sama. Sebelumnya keduanya memakai kosakata yang
persis sama padahal berbeda pada 22,6% pasangan.

### 3.4 Verifikasi

**`siap reproduce`** — memuat ulang parameter dan seed yang **run itu sendiri
catat**, menghitung ulang setiap skor, lalu membandingkannya baris per baris pada
presisi yang disimpan database.

Terakhir diverifikasi: run #47, 60 seri, **78.274 skor, semuanya identik.**
Perbandingannya *tanpa toleransi* — sengaja. Skor yang berbeda di desimal kedua
belas dengan seed dan data yang sama berarti ada sesuatu yang benar-benar
non-deterministik, dan toleransi justru akan menyembunyikan bug yang ingin
ditemukan.

**`siap doctor`** — memeriksa kelengkapan skema, posisi RLS, dan data referensi.
Jalankan ini kalau ada yang terasa aneh, sebelum menebak-nebak.

**`siap runs`** — daftar run analisis, dan bisa merapikan run yang terlantar.

### 3.5 Untuk paper

| Perintah | Gunanya |
|---|---|
| `siap gt-pool` | Membuat kumpulan 399 kandidat ground-truth secara berstrata |
| `siap kappa` | Cohen's kappa antar dua annotator — gerbang penghenti M7 |
| `siap ablate` | Sensitivitas parameter |
| `siap export` | Gambar dan tabel ke `paper-exports/` |

## 4. Perintah dan kapan dipakai

**Sekali saja, saat menyiapkan:**

```bash
siap config      # validasi engine/config/*.yaml, tanpa perlu database
siap migrate     # jalankan supabase/migrations/*.sql berurutan
siap seed        # muat data referensi dari engine/config/*.yaml
siap doctor      # pastikan skema, RLS, dan seed sudah benar
```

**Rutin harian** (sudah otomatis, lihat §5):

```bash
siap ingest
siap trends
siap preprocess && siap analyze && siap cluster && siap seasonal && siap fuse
```

**Saat mau menghasilkan angka untuk paper:**

```bash
siap gt-pool          # sebelum pelabelan
siap kappa            # setelah kedua annotator selesai
siap ablate
siap export
```

## 5. Yang jalan otomatis

`.github/workflows/daily.yml`, setiap hari **02:00 WIB** (19:00 UTC hari
sebelumnya). Jam itu dipilih karena portal Indonesia menerbitkan sepanjang hari
kerja, jadi menjalankannya lewat tengah malam lokal mendapat angka yang sudah
mengendap.

Dua job berurutan:

1. **`ingest`** — ambil harga, segarkan sinyal permintaan, lalu `siap doctor`
2. **`analyse`** — `preprocess → analyze → cluster → seasonal → fuse`, lalu
   `siap reproduce`

**`analyse` punya `needs: ingest` dan sengaja TIDAK punya `if: always()`.** Kalau
ingest gagal, analisis tidak dijalankan. Alasannya: `preprocess` melakukan
truncate dan menulis ulang seri harian, dan melakukannya di atas ingest yang
gagal berarti membangun ulang semuanya dari data yang tidak diperiksa siapa pun.

Jadi kalau scraper bermasalah, yang terjadi adalah **peringatan kemarin tetap
tampil** — itu mode kegagalan yang benar. Peringatan yang dihitung ulang dari
hari yang separuh terisi bukan.

Dashboard me-*revalidate* tiap 30 menit, jadi peringatan baru muncul dalam
setengah jam setelah analisis selesai, tanpa perlu deploy ulang.

**Menjalankan manual tanpa menunggu 02:00:** Actions → *Daily ingestion* → *Run
workflow*. Ada dua input opsional, `obs_date` dan `sources`. Ingat bahwa run ini
**menulis ke database produksi**.

## 6. Cara Grace dan Roy mengakses `/lab`

Ini bagian yang paling mudah salah, karena keliru sedikit saja bisa merusak
kesahihan angka κ. Kerjakan berurutan.

### Langkah 1 — Pastikan pipeline sudah mutakhir

Kumpulan kandidat harus diambil dari data yang benar-benar akan mereka nilai.
Kalau ada perubahan di hulu (backfill baru, perubahan preprocessing), jalankan
`preprocess → analyze → cluster → seasonal → fuse` lalu `siap gt-pool --redraw`
**sebelum** pelabelan dimulai.

Begitu satu label sudah masuk, kumpulan itu **tidak boleh** diambil ulang, dan
`siap gt-pool --redraw` akan menolak — itu perilaku yang disengaja.

### Langkah 2 — Buat dua akun

Dashboard Supabase → **Authentication → Users → Add user**. Isi password, dan
centang *Auto Confirm User* supaya tidak perlu pengiriman email.

Akun dibuat manual dengan sengaja. **Tidak ada halaman pendaftaran**: himpunan
annotator adalah dua orang yang disepakati dalam protokol, bukan siapa pun yang
menemukan URL-nya.

### Langkah 3 — Daftarkan sebagai annotator

```bash
siap lab-annotator --email grace@example.com --code A1
siap lab-annotator --email roy@example.com   --code A2
siap lab-annotator                              # tampilkan daftar, untuk memastikan
```

Kode bersifat pseudonim karena dibatasi pola `^[A-Z][0-9]{1,2}$` — kode ini
muncul di paper, jadi tidak boleh berupa nama orang.

**Daftarkan tepat dua orang yang akan melabel.** Cohen's κ terdefinisi untuk
sepasang. Kalau orang ketiga terdaftar dan ikut melabel, `siap kappa` akan
menolak, bukan diam-diam memilih dua dan mengabaikan yang ketiga.

> **Catatan untuk kondisi proyek ini.** A3 adalah kamu, berperan sebagai
> adjudicator, dan **tidak akan melabel**. Itu aman: `siap kappa` menghitung
> annotator yang punya baris di `gt_labels`, bukan yang terdaftar. Selama kamu
> tidak menyimpan satu label pun, `siap kappa` berjalan tanpa perlu argumen apa
> pun. Kalau sampai terpencet satu label, jalankan `siap kappa --a A1 --b A2`
> atau hapus baris itu.

### Langkah 4 — Buktikan kedua daftar label saling terisolasi

```bash
siap lab-check      # harus lolos 14/14
```

Perintah ini **menyamar** menjadi masing-masing annotator terhadap database
sungguhan, lalu mencoba membaca kumpulan kandidat, membaca label annotator lain,
dan menulis dengan kode annotator lain. Kalau ada satu saja yang berhasil,
**jangan mulai** — κ akan mengukur kontaminasi, bukan kesepakatan.

### Langkah 5 — Kirim ini ke mereka

> Pelabelan ground truth SIAP-PANGAN
> <https://talks-siap-pangan.vercel.app/lab>
> Masuk pakai email dan kata sandi yang sudah dibuat koordinator.
>
> Tiga hal penting:
> 1. Kerjakan sendiri. Jangan mendiskusikan kandidat dengan annotator lain
>    sampai kedua daftar selesai — nilai kesepakatan hanya bermakna kalau kedua
>    penilaian independen.
> 2. Label yang sudah disimpan tidak bisa diubah.
> 3. Kalau ragu, pilih "Ragu". Menebak lebih merusak daripada mengaku tidak
>    yakin.
>
> Panduan lengkap ada di dalam aplikasi (tombol "Panduan lengkap").

### Yang perlu kamu tahu soal pengalaman mereka

- **Tidak wajib selesai 399 sekaligus.** Setiap label disimpan sendiri-sendiri
  saat itu juga. Antrean otomatis melewati yang sudah mereka labeli, jadi
  membuka `/lab` lagi langsung melanjutkan dari titik terakhir. Menutup tab aman.
- **Urutannya tetap.** Memakai `shuffle_key` yang seeded, jadi tidak diacak ulang
  tiap sesi.
- **Label tidak bisa diubah.** Ada batasan unik per (kandidat, annotator);
  percobaan kedua ditolak dengan pesan yang jelas. Bisa dilanjut ≠ bisa
  diperbaiki. Karena itu "Ragu" adalah jawaban yang sah, bukan kegagalan.
- **Progres hanya miliknya sendiri.** Masing-masing melihat hitungannya sendiri,
  **tidak** melihat hitungan yang lain — supaya mereka tidak saling mengejar tempo.
- **Pintasan papan tuntas:** `1` tidak wajar, `2` wajar, `3` ragu, `Enter` simpan.
- Kandidat diambil 20 per batch, jadi ringan di koneksi lemah.

Karena boleh dicicil, ada risiko yang justru bertambah: makin panjang rentang
waktunya, makin besar peluang mereka mendiskusikan kandidat sebelum keduanya
selesai. **Ulangi aturan "jangan diskusi dulu" secara berkala**, jangan disebut
sekali saja di awal.

### Kalau dicicil, apakah datanya jadi beda? Tidak.

Pertanyaan yang wajar: pipeline jalan tiap hari 02:00 WIB, jadi kalau Grace
melabel tanggal 30 lalu lanjut tanggal 2, bukankah yang dia lihat sudah berubah —
sementara redraw dilarang setelah label pertama?

Tidak berubah, karena **yang dilihat annotator dibekukan saat pool ditarik**:

1. `siap gt-pool` memateralisasi jendela harga tiap kandidat ke dalam kolom
   `gt_candidates.context` (JSONB: `window`, `baseline`, `focus_date`,
   `definition_pct`), bersama `shuffle_key` untuk urutan tetap dan
   `generated_by_run` yang mencatat run analisis pembuatnya.
2. Fungsi `lab_queue` mengembalikan kolom `context` itu — bukan hasil query ulang
   ke tabel harga.
3. `web/src/app/lab/PriceWindow.tsx` tidak memuat data sama sekali: tidak ada
   `fetch`, `supabase`, `.from(`, maupun `.rpc(`. Dia murni merender props yang
   diberikan `page.tsx:326`.

Jadi run harian menulis ke `price_daily_unified` dan `anomaly_scores` — dua tabel
yang konsol pelabelan **tidak pernah baca**. Kandidat nomor 200 hari ini adalah
kandidat nomor 200 yang sama persis dua minggu lagi.

**Aturan redraw itu tentang satu momen: sebelum label pertama.** Snapshot yang
dibekukan harus mewakili data yang sedang diteliti. Setelah dibekukan dan
pelabelan dimulai, pembekuan itu justru properti yang diinginkan — dan itu
sebabnya `--redraw` menolak sesudahnya. Bukan karena data yang bergerak
membatalkan label, tapi karena menarik ulang akan membuang snapshot yang
label-label itu tunjuk, meninggalkan label yang mengacu ke kandidat yang sudah
tidak ada. Dua aturan yang terlihat bertabrakan sebenarnya satu: **bekukan
sekali, di saat yang tepat, lalu jangan diutak-utik.**

> **Sampaikan ini ke annotator.** Jangan membandingkan apa yang terlihat di
> `/lab` dengan dashboard publik. Lab dibekukan di waktu pool ditarik, dashboard
> terus maju setiap hari — makin lama pelabelan berjalan, makin jauh keduanya
> berbeda, dan itu **bukan** kekeliruan. Nilai apa yang ada di layar lab, jangan
> menyilang-cek ke dashboard.

### Langkah 6 — Setelah keduanya selesai

```bash
siap kappa
```

**κ ≥ 0.60 adalah gerbang, bukan metrik.** Di bawah itu, brief menyatakan jangan
lanjut: perbaiki definisinya, labeli ulang, dan laporkan kedua putaran di paper.

Tidak ada satu pun angka di hilir label — presisi, recall, F1, perbandingan
empat-arm — yang bisa dihitung sebelum ini selesai, dan tidak ada yang
diestimasi sementara.

### `/lab` itu dilindungi apa?

Bukan dilindungi karena disembunyikan. Dia dilindungi **RLS**: permintaan tanpa
sesi yang sah tidak mendapat apa pun, siapa pun yang meminta. Akses ke tabel
`gt_labels` diberi izin INSERT tanpa SELECT, sehingga seorang annotator **secara
fisik tidak bisa** membaca penilaian annotator lain. Antreannya juga membaca view
yang buta-strata, jadi tidak bisa membocorkan dari strata mana suatu kandidat
diambil.

`robots.txt` melarang `/lab` supaya tidak muncul di hasil pencarian, tapi itu
kebersihan, bukan pengamanan.

## 7. Kalau ada yang gagal

| Gejala | Lihat ke mana |
|---|---|
| Dashboard kosong | Analisis belum dijalankan atas database ini. Jalankan rantai `preprocess → … → fuse` |
| Angka di dashboard basi | Cek Actions → *Daily ingestion*. Kalau merah, baca log job `ingest` |
| Dashboard error saat dibuka | Supabase tersendat. Halaman error **sengaja tidak** menampilkan angka cache — harga usang yang disajikan sebagai harga terkini adalah kegagalan yang sistem ini ada untuk mencegahnya |
| Satu sumber selalu gagal | `siap coverage --detail`, lalu [sources.md](sources.md) untuk keanehan portal itu |
| Annotator melihat antrean kosong | Akunnya belum punya baris `lab_annotators`. Jalankan `siap lab-annotator` |
| `siap kappa` menolak | Lebih dari dua orang punya label. Lihat §6 langkah 3 |
| Ragu apakah database sehat | `siap doctor` |

## 8. Batas-batas yang perlu kamu tahu sebelum ditanya

Ini bukan daftar kekurangan yang harus disembunyikan. Semuanya sudah tercatat di
[changelog.md](changelog.md) dengan alasannya, supaya bisa **dipertahankan**
bukan ditemukan orang lain.

- **`panelharga` (Badan Pangan Nasional) tidak aktif** — seluruh endpointnya
  bermasalah di sisi mereka. Yang aktif empat sumber, bukan lima.
- **`jogja` hanya maju ke depan** — tidak ada arsip yang bisa diambil, jadi seri
  ini mulai dari saat pengumpulan dimulai, bukan tiga tahun ke belakang.
- **Delapan seri masih menyisakan selisih 5–9%** setelah penautan sumber — cabai,
  bawang merah, bawang putih. Di seri itu, hari-hari ketika jumlah sumber yang
  melapor berubah masih lebih gaduh. `source_offsets.ratio_cv_pct`
  mengidentifikasinya.
- **Setiap run anomali berstatus `partial`** — 12 seri Kota Yogyakarta hanya punya
  riwayat satu minggu, sementara Isolation Forest butuh minimal 60 baris. Ini
  bukan kegagalan yang tersembunyi: statusnya memang dilaporkan `partial`.
- **Belum ada angka evaluasi.** Presisi, recall, F1, dan perbandingan empat-arm
  menunggu pelabelan Grace dan Roy plus gerbang κ. Tidak ada yang diestimasi
  sementara, dan itu disengaja.
- **Sistem ini tidak meramal.** Kalau ada pertanyaan tentang harga besok,
  jawabannya bukan "belum sempat", tapi "di luar ruang lingkup, dan itu keputusan
  desain".
