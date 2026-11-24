from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class IdentitasKK(Base):
    __tablename__ = "tbl_identitasKK"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nomor_kk: Mapped[str] = mapped_column(String(16), unique=True, index=True, default="")
    nama_kepala_keluarga: Mapped[str] = mapped_column(String(150), default="")
    alamat: Mapped[str] = mapped_column(String(250), default="")
    rt: Mapped[str] = mapped_column(String(5), default="")
    rw: Mapped[str] = mapped_column(String(5), default="")
    kode_pos: Mapped[str] = mapped_column(String(10), default="")
    desa_kelurahan: Mapped[str] = mapped_column(String(100), default="")
    kecamatan: Mapped[str] = mapped_column(String(100), default="")
    kabupaten_kota: Mapped[str] = mapped_column(String(100), default="")
    provinsi: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    anggota: Mapped[list["AnggotaKeluargaKK"]] = relationship(
        back_populates="identitas", cascade="all, delete-orphan"
    )


class AnggotaKeluargaKK(Base):
    __tablename__ = "tbl_anggotaKeluargaKK"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identitas_kk_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_identitasKK.id", ondelete="CASCADE"), index=True
    )
    nik: Mapped[str] = mapped_column(String(16), default="")
    nama_lengkap: Mapped[str] = mapped_column(String(150), default="")
    jenis_kelamin: Mapped[str] = mapped_column(String(30), default="")
    tempat_lahir: Mapped[str] = mapped_column(String(100), default="")
    tanggal_lahir: Mapped[str] = mapped_column(String(30), default="")
    agama: Mapped[str] = mapped_column(String(50), default="")
    pendidikan: Mapped[str] = mapped_column(String(100), default="")
    jenis_pekerjaan: Mapped[str] = mapped_column(String(100), default="")
    status_perkawinan: Mapped[str] = mapped_column(String(50), default="")
    status_hubungan_dalam_keluarga: Mapped[str] = mapped_column(String(50), default="")
    kewarganegaraan: Mapped[str] = mapped_column(String(50), default="")
    no_paspor: Mapped[str] = mapped_column(String(50), default="")
    no_kitas_kitap: Mapped[str] = mapped_column(String(50), default="")
    nama_ayah: Mapped[str] = mapped_column(String(150), default="")
    nama_ibu: Mapped[str] = mapped_column(String(150), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    identitas: Mapped[IdentitasKK] = relationship(back_populates="anggota")
