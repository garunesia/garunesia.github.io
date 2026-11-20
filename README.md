# Papan Komentator Garunesia

Leaderboard otomatis untuk komentator tercepat di video YouTube Garunesia. Gratis, tanpa server: GitHub Actions menghitung, GitHub Pages menampilkan.

## Aturan poin

- Hanya **5 komentator pertama** dalam **24 jam** sejak video tayang yang dapat poin: 5, 4, 3, 2, 1.
- Komentar dari channel Garunesia sendiri tidak dihitung.
- Satu orang dihitung sekali per video. Balasan (reply) tidak dihitung.
- Komentar minimal 2 kata, jadi emoji atau "first" saja tidak dihitung.
- Poin dikunci setelah 24 jam. Ada peringkat **bulanan** (mulai ulang setiap tanggal 1) dan **sepanjang masa**.
- Video baru masuk papan setelah jendela 24 jamnya tutup (dicek setiap jam).

Semua angka di atas bisa diubah di `config.json`.

## Setup (sekali saja, ±20 menit)

### 1. Buat API key YouTube

1. Buka https://console.cloud.google.com dan login dengan akun Google mana saja.
2. Buat project baru, misalnya `garunesia-web`.
3. Menu **APIs & Services → Library**, cari **YouTube Data API v3**, klik **Enable**.
4. Menu **APIs & Services → Credentials → Create credentials → API key**. Salin key-nya.
5. (Disarankan) Klik key tersebut, di **API restrictions** pilih *Restrict key* → centang YouTube Data API v3 saja → Save.

Tidak perlu kartu kredit. Kuota gratisnya 10.000 unit per hari, sedangkan script ini hanya memakai sekitar 30–50 unit per hari.

### 2. Cari ID channel Garunesia

Buka YouTube Studio → **Settings → Channel → Advanced settings**. Salin **Channel ID** (diawali `UC`).

### 3. Buat repo GitHub

1. Daftar/login di https://github.com. Nama akun `garunesia` akan membuat alamat web menjadi `garunesia.github.io/...`.
2. Klik **New repository**, beri nama misalnya `papan` (alamatnya nanti `namaakun.github.io/papan`). Pilih **Public**.
   - Kalau repo dinamai persis `namaakun.github.io`, alamatnya menjadi `namaakun.github.io` tanpa tambahan.
3. Klik **uploading an existing file**, lalu unggah **seluruh isi** folder ini (termasuk folder `.github`). Kalau folder `.github` tidak ikut terunggah lewat browser, buat file baru dengan nama `.github/workflows/update.yml` dan tempel isinya.

### 4. Isi pengaturan

1. Di repo, buka `config.json` → ikon pensil → ganti `GANTI_DENGAN_ID_CHANNEL_GARUNESIA` dengan Channel ID.
2. `start_date` = tanggal mulai dihitung (format `TAHUN-BULAN-TANGGAL`), saat ini `2026-10-01`. Video sebelum tanggal ini tidak dihitung. Boleh diisi tanggal lampau untuk ikut menghitung video lama, karena waktu komentar tetap tercatat di YouTube.
3. Commit.

### 5. Simpan API key sebagai rahasia

Repo → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `YT_API_KEY`
- Secret: tempel API key dari langkah 1.

### 6. Nyalakan GitHub Pages

Repo → **Settings → Pages** → di **Source** pilih **GitHub Actions**.

### 7. Jalankan pertama kali

Repo → tab **Actions** → **Update leaderboard** → **Run workflow** (tombol ini juga bisa dipakai kapan saja untuk memperbarui papan tanpa menunggu jadwal). Setelah centang hijau (±1 menit), website tampil di alamat yang tertera di Settings → Pages.

Setelah itu semuanya otomatis setiap jam.

## Pengaturan di `config.json`

| Kunci | Arti |
| --- | --- |
| `channel_id` | ID channel Garunesia (komentarnya tidak dihitung) |
| `start_date` | Video yang tayang mulai tanggal ini yang dihitung (WIB) |
| `window_hours` | Lama jendela komentar, bawaan 24 jam |
| `points` | Poin per urutan. `[5,4,3,2,1]` berarti 5 orang pertama |
| `min_words` | Minimal jumlah kata komentar. Isi `1` untuk mematikan aturan ini |
| `leaderboard_size` | Jumlah orang di papan, bawaan 50 |
| `exclude_channels` | Daftar Channel ID yang tidak ikut dihitung (mis. akun kedua, atau orang yang minta tidak ditampilkan) |

Setelah mengubah aturan untuk video yang sudah dikunci, hapus file `data/state.json` lalu jalankan workflow manual supaya semua video dihitung ulang.

## Catatan

- Komentar yang tertahan di **"Ditahan untuk ditinjau"** di YouTube Studio tidak terbaca sampai disetujui. Kalau disetujui setelah video dikunci, komentar itu tidak dihitung.
- Video yang dihapus atau dijadikan privat otomatis dikeluarkan dari hitungan.
- GitHub kadang menunda jadwal otomatis 5–20 menit saat ramai. Urutan tetap akurat karena memakai waktu asli komentar.
- GitHub mematikan jadwal otomatis jika repo tidak ada aktivitas selama 60 hari. Selama rutin upload, repo selalu aktif karena hasil hitungan tersimpan otomatis.

## Struktur file

```
config.json                 pengaturan
scripts/update.py           penghitung (Python, tanpa library tambahan)
.github/workflows/update.yml jadwal otomatis + terbitkan website
data/state.json             hasil per video (dibuat otomatis)
docs/index.html             halaman website (class Tailwind)
styles/app.css              warna, font & sumber Tailwind; docs/app.css dibuat otomatis saat deploy
docs/data/leaderboard.json  data yang dibaca website (dibuat otomatis)
docs/logo.png               logo Garunesia
```
