import base64
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import models
from .database import Base, engine, get_db
from .ocr import read_kk_image

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
pending_drafts: dict[str, dict] = {}
DRAFT_DIR = BASE_DIR / "data" / "drafts"
DRAFT_TTL = 24 * 60 * 60
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def _draft_path(draft_id: str) -> Path:
    return DRAFT_DIR / f"{draft_id}.json"


def _save_draft(draft_id: str, draft: dict) -> None:
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    _draft_path(draft_id).write_text(
        json.dumps({"created_at": time.time(), "draft": draft}), encoding="utf-8"
    )
    pending_drafts[draft_id] = draft


def _load_drafts() -> None:
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    for path in DRAFT_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            continue
        if time.time() - payload.get("created_at", 0) > DRAFT_TTL:
            path.unlink(missing_ok=True)
            continue
        pending_drafts[path.stem] = payload["draft"]


def _delete_draft(draft_id: str) -> None:
    pending_drafts.pop(draft_id, None)
    _draft_path(draft_id).unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _load_drafts()
    Base.metadata.create_all(bind=engine)
    # create_all creates missing tables but does not add fields to an existing
    # SQLite database; keep this tiny migration so existing student data stays.
    migrations = {
        "tbl_identitasKK": {"nama_kepala_keluarga": "VARCHAR(150) NOT NULL DEFAULT ''"},
        "tbl_anggotaKeluargaKK": {
            "no_paspor": "VARCHAR(50) NOT NULL DEFAULT ''",
            "no_kitas_kitap": "VARCHAR(50) NOT NULL DEFAULT ''",
        },
    }
    with engine.begin() as connection:
        for table, columns in migrations.items():
            existing = {column["name"] for column in inspect(connection).get_columns(table)}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'))
    yield


app = FastAPI(title="Pendataan Kartu Keluarga", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


def page(request: Request, name: str, **context):
    return templates.TemplateResponse(request=request, name=name, context=context)


def clean(value: str | None) -> str:
    return (value or "").strip()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return RedirectResponse("/kk", status_code=303)


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return page(request, "upload.html")


@app.post("/upload", response_class=HTMLResponse)
async def upload_image(request: Request, image: UploadFile = File(...)):
    if image.content_type not in ALLOWED_TYPES:
        return page(request, "upload.html", error="Gunakan file JPG, PNG, atau WebP.")
    content = await image.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        return page(request, "upload.html", error="Ukuran file maksimal 8 MB.")
    if not content:
        return page(request, "upload.html", error="File gambar kosong.")

    draft = read_kk_image(content)
    draft_id = uuid.uuid4().hex
    _save_draft(draft_id, {
        "image_data": base64.b64encode(content).decode("ascii"),
        "image_type": image.content_type,
        **draft,
    })
    return page(request, "confirm.html", draft_id=draft_id, **pending_drafts[draft_id])


@app.post("/confirm")
async def confirm_data(
    request: Request,
    draft_id: str = Form(...),
    nomor_kk: str = Form(""), nama_kepala_keluarga: str = Form(""), alamat: str = Form(""), rt: str = Form(""),
    rw: str = Form(""), kode_pos: str = Form(""), desa_kelurahan: str = Form(""),
    kecamatan: str = Form(""), kabupaten_kota: str = Form(""), provinsi: str = Form(""),
    nik: list[str] = Form([]), nama_lengkap: list[str] = Form([]),
    jenis_kelamin: list[str] = Form([]), tempat_lahir: list[str] = Form([]),
    tanggal_lahir: list[str] = Form([]), agama: list[str] = Form([]),
    pendidikan: list[str] = Form([]), jenis_pekerjaan: list[str] = Form([]),
    status_perkawinan: list[str] = Form([]), status_hubungan_dalam_keluarga: list[str] = Form([]),
    kewarganegaraan: list[str] = Form([]), no_paspor: list[str] = Form([]),
    no_kitas_kitap: list[str] = Form([]), nama_ayah: list[str] = Form([]),
    nama_ibu: list[str] = Form([]), db: Session = Depends(get_db),
):
    if draft_id not in pending_drafts:
        raise HTTPException(status_code=410, detail="Draft kedaluwarsa. Unggah gambar kembali.")
    if not clean(nomor_kk):
        raise HTTPException(status_code=422, detail="Nomor KK wajib diisi.")

    identitas_values = {
        "nomor_kk": clean(nomor_kk), "nama_kepala_keluarga": clean(nama_kepala_keluarga),
        "alamat": clean(alamat), "rt": clean(rt), "rw": clean(rw),
        "kode_pos": clean(kode_pos), "desa_kelurahan": clean(desa_kelurahan),
        "kecamatan": clean(kecamatan), "kabupaten_kota": clean(kabupaten_kota),
        "provinsi": clean(provinsi),
    }
    identitas = models.IdentitasKK(**identitas_values)
    member_fields = {
        "nik": nik, "nama_lengkap": nama_lengkap, "jenis_kelamin": jenis_kelamin,
        "tempat_lahir": tempat_lahir, "tanggal_lahir": tanggal_lahir, "agama": agama,
        "pendidikan": pendidikan, "jenis_pekerjaan": jenis_pekerjaan,
        "status_perkawinan": status_perkawinan,
        "status_hubungan_dalam_keluarga": status_hubungan_dalam_keluarga,
        "kewarganegaraan": kewarganegaraan, "no_paspor": no_paspor,
        "no_kitas_kitap": no_kitas_kitap, "nama_ayah": nama_ayah, "nama_ibu": nama_ibu,
    }
    count = max((len(values) for values in member_fields.values()), default=0)
    submitted_members = []
    for i in range(count):
        data = {field: clean(values[i]) if i < len(values) else "" for field, values in member_fields.items()}
        submitted_members.append(data)
        if any(data.values()):
            identitas.anggota.append(models.AnggotaKeluargaKK(**data))
    db.add(identitas)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        draft = pending_drafts[draft_id]
        return page(
            request, "confirm.html", draft_id=draft_id,
            error="Nomor KK tersebut sudah terdaftar.",
            identitas=identitas_values, anggota=submitted_members,
            notice=draft.get("notice", ""), raw_text=draft.get("raw_text", ""),
            image_type=draft["image_type"], image_data=draft["image_data"],
            check_fields=draft.get("check_fields", []),
        )
    _delete_draft(draft_id)
    return RedirectResponse(f"/kk/{identitas.id}?saved=1", status_code=303)


@app.get("/kk", response_class=HTMLResponse)
def kk_list(request: Request, q: str = "", db: Session = Depends(get_db)):
    stmt = select(models.IdentitasKK).options(selectinload(models.IdentitasKK.anggota))
    if clean(q):
        term = f"%{clean(q)}%"
        stmt = stmt.where(or_(
        models.IdentitasKK.nomor_kk.like(term),
        models.IdentitasKK.nama_kepala_keluarga.like(term),
        models.IdentitasKK.alamat.like(term),
    ))
    rows = db.scalars(stmt.order_by(models.IdentitasKK.updated_at.desc())).all()
    return page(request, "list.html", rows=rows, q=q)


@app.get("/kk/{kk_id}", response_class=HTMLResponse)
def kk_detail(request: Request, kk_id: int, saved: int = 0, error: str | None = None, db: Session = Depends(get_db)):
    row = db.scalar(select(models.IdentitasKK).options(selectinload(models.IdentitasKK.anggota)).where(models.IdentitasKK.id == kk_id))
    if not row:
        raise HTTPException(404, "Data KK tidak ditemukan")
    return page(request, "detail.html", row=row, saved=bool(saved), error=error)


@app.post("/kk/{kk_id}/update")
async def update_kk(kk_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.get(models.IdentitasKK, kk_id)
    if not row:
        raise HTTPException(404, "Data KK tidak ditemukan")
    form = await request.form()
    for field in ("nomor_kk", "nama_kepala_keluarga", "alamat", "rt", "rw", "kode_pos", "desa_kelurahan", "kecamatan", "kabupaten_kota", "provinsi"):
        setattr(row, field, clean(str(form.get(field, ""))))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return kk_detail(request, kk_id, db=db, error="Nomor KK sudah digunakan.")
    return RedirectResponse(f"/kk/{kk_id}", status_code=303)


@app.post("/kk/{kk_id}/delete")
def delete_kk(kk_id: int, db: Session = Depends(get_db)):
    row = db.get(models.IdentitasKK, kk_id)
    if row:
        db.delete(row)
        db.commit()
    return RedirectResponse("/kk", status_code=303)


@app.post("/kk/{kk_id}/anggota")
async def add_member(kk_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.get(models.IdentitasKK, kk_id)
    if not row:
        raise HTTPException(404, "Data KK tidak ditemukan")
    form = await request.form()
    fields = ("nik", "nama_lengkap", "jenis_kelamin", "tempat_lahir", "tanggal_lahir", "agama", "pendidikan", "jenis_pekerjaan", "status_perkawinan", "status_hubungan_dalam_keluarga", "kewarganegaraan", "no_paspor", "no_kitas_kitap", "nama_ayah", "nama_ibu")
    data = {field: clean(str(form.get(field, ""))) for field in fields}
    if any(data.values()):
        row.anggota.append(models.AnggotaKeluargaKK(**data))
        db.commit()
    return RedirectResponse(f"/kk/{kk_id}#anggota", status_code=303)


@app.post("/anggota/{member_id}/update")
async def update_member(member_id: int, request: Request, db: Session = Depends(get_db)):
    member = db.get(models.AnggotaKeluargaKK, member_id)
    if not member:
        raise HTTPException(404, "Anggota tidak ditemukan")
    form = await request.form()
    fields = ("nik", "nama_lengkap", "jenis_kelamin", "tempat_lahir", "tanggal_lahir", "agama", "pendidikan", "jenis_pekerjaan", "status_perkawinan", "status_hubungan_dalam_keluarga", "kewarganegaraan", "no_paspor", "no_kitas_kitap", "nama_ayah", "nama_ibu")
    for field in fields:
        setattr(member, field, clean(str(form.get(field, ""))))
    parent_id = member.identitas_kk_id
    db.commit()
    return RedirectResponse(f"/kk/{parent_id}#anggota", status_code=303)


@app.post("/anggota/{member_id}/delete")
def delete_member(member_id: int, db: Session = Depends(get_db)):
    member = db.get(models.AnggotaKeluargaKK, member_id)
    if member:
        parent_id = member.identitas_kk_id
        db.delete(member)
        db.commit()
        return RedirectResponse(f"/kk/{parent_id}#anggota", status_code=303)
    raise HTTPException(404, "Anggota tidak ditemukan")
