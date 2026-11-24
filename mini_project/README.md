# OCR Kartu Keluarga — rancangan MVP

Mini project web untuk membaca data dari foto/scan Kartu Keluarga (KK), meminta pengguna mengoreksi hasil OCR, lalu menyimpan identitas KK dan anggota keluarga.

## Alur pengguna

1. **Input** — unggah JPG/PNG, lihat pratinjau, lalu mulai pembacaan.
2. **Konfirmasi** — tinjau data identitas dan setiap anggota dalam form editable; koreksi sebelum menyimpan.
3. **Daftar KK** — cari berdasarkan nomor KK/nama kepala keluarga, buka detail, ubah atau hapus.
4. **Detail KK** — tampilkan data identitas beserta anggota; anggota dapat ditambah, diubah, atau dihapus.

## Rancangan teknis

- **Backend:** Python + FastAPI; halaman HTML dirender dengan Jinja2 dan interaksi ringan memakai HTMX/JavaScript. Ini menghindari kebutuhan frontend build system untuk MVP.
- **Database:** SQLite untuk demo lokal, diakses melalui SQLAlchemy. Struktur tetap mudah dipindahkan ke PostgreSQL.
- **Computer vision:** model Roboflow `kartu-keluarga-ocr/7` mendeteksi lokasi field (object detection). Deteksi bounding box perlu dilanjutkan dengan OCR teks pada crop, lalu hasilnya dipetakan ke field. Model deteksi saja tidak menghasilkan nilai seperti NIK/nama.
- **OCR:** RapidOCR lokal membaca teks dari gambar; parser awal memetakan data KK dan baris anggota dari label/posisi tabel. Roboflow dapat ditambahkan untuk deteksi field yang lebih konsisten.
- **Keamanan data:** API key hanya di backend melalui `.env`; validasi tipe/ukuran upload; jangan commit foto KK, hasil OCR, `.env`, atau database berisi data nyata.

## Model data (dua tabel inti)

### `tbl_identitasKK`

- `id` (PK)
- `nomor_kk` (unik)
- `nama_kepala_keluarga`, `alamat`, `rt`, `rw`, `desa_kelurahan`, `kecamatan`, `kabupaten_kota`, `kode_pos`, `provinsi`
- `created_at`, `updated_at`

### `tbl_anggotaKeluargaKK`

- `id` (PK)
- `identitas_kk_id` (FK ke `tbl_identitasKK.id`, ON DELETE CASCADE)
- `nik`, `nama_lengkap`, `jenis_kelamin`, `tempat_lahir`, `tanggal_lahir`
- `agama`, `pendidikan`, `jenis_pekerjaan`, `status_perkawinan`, `status_hubungan_dalam_keluarga`
- `kewarganegaraan`, `no_paspor`, `no_kitas_kitap`, `nama_ayah`, `nama_ibu`
- `created_at`, `updated_at`

Dokumen sumber dan draft OCR sebaiknya tidak dipaksakan menjadi tabel ketiga karena kebutuhan awal menetapkan dua tabel. Draft dapat disimpan sementara di server/session, lalu baris hanya dibuat setelah pengguna menekan **Simpan**.

## Tahapan implementasi

1. Kerangka FastAPI, model SQLAlchemy, dan halaman daftar/detail dengan CRUD.
2. Form unggah dan halaman konfirmasi dengan data contoh (tanpa integrasi model dulu).
3. Adapter Roboflow untuk deteksi + adapter OCR untuk membaca teks crop.
4. Validasi, penanganan field kosong/duplikat, dan penyempurnaan UX.

## Menjalankan aplikasi

Di PowerShell dari folder `mini_project`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Buka `http://127.0.0.1:8000`. Database SQLite dibuat otomatis di `data/kartu_keluarga.db` saat aplikasi pertama berjalan. Upload menjalankan OCR lokal dan mengisi field yang berhasil dikenali ke form konfirmasi. Draft upload disimpan sementara di memori proses dan hilang ketika server dimulai ulang.

## Status prototipe

- Sudah ada halaman input, konfirmasi, daftar/pencarian KK, detail KK, edit/hapus identitas, serta tambah/edit/hapus anggota.
- Draft baru masuk ke database sesudah tombol **Simpan data KK** ditekan.
- Validasi awal upload menerima JPG/PNG/WebP hingga 8 MB; setiap KK perlu nomor KK unik.
- OCR lokal sudah terhubung. Parser membaca header identitas sebagai pasangan label/nilai, lalu memasangkan baris bernomor sama pada tabel anggota bagian atas dan bawah. Hasil tetap perlu dikoreksi pengguna.
- Header KK disimpan dengan nama kepala keluarga. Data anggota mencakup nomor paspor, KITAS/KITAP, serta nama ayah dan ibu.
- Saat aplikasi mulai, kolom baru ditambahkan otomatis ke database SQLite lama tanpa menghapus data yang sudah ada.
- Integrasi Roboflow berikutnya dapat memakai bounding box field agar pemetaan kolom dan baris anggota lebih presisi. Hosted inference perlu API key yang disimpan di `.env`, bukan di frontend.

## Catatan dataset/model

Halaman Roboflow yang ditautkan menampilkan 31 kelas dan model object-detection `kartu-keluarga-ocr/7`; metrik yang ditampilkan adalah mAP/precision/recall untuk deteksi. Halaman menampilkan 109 images, sementara versi model terkait menyebut dataset 259 images. Lisensinya CC BY 4.0. Periksa kembali label serta lisensi versi yang akan dipakai sebelum mengunduh/melatih dataset.
