"""Local OCR for KK uploads, with a conservative editable-field parser.

The Roboflow dataset model is still useful for locating field regions, but its
hosted inference needs credentials. This first local pass reads the complete
image and pre-fills values that can be identified from text and table position.
"""

from dataclasses import dataclass
import re
from typing import Any

import cv2
import numpy as np
from rapidocr import RapidOCR


_engine: RapidOCR | None = None


@dataclass
class OCRLine:
    text: str
    x: float
    y: float
    score: float


def _ocr_engine() -> RapidOCR:
    global _engine
    if _engine is None:
        _engine = RapidOCR()
    return _engine


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _clean_cell(text: str) -> str:
    """Strip column reference markers such as (11) from OCR values."""
    text = re.sub(r"\(\s*\d{1,2}\s*\)", " ", text)
    text = re.sub(r"\[\s*\d{1,2}\s*\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" :;|,.-")
    return "" if re.fullmatch(r"[-–—.]+", text) else text


def _read_lines(image: np.ndarray) -> list[OCRLine]:
    result = _ocr_engine()(image)
    lines: list[OCRLine] = []
    if result is None or result.boxes is None or len(result.boxes) == 0:
        return lines
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        points = np.asarray(box)
        lines.append(OCRLine(
            text=str(text).strip(),
            x=float(points[:, 0].mean()) / image.shape[1],
            y=float(points[:, 1].mean()) / image.shape[0],
            score=float(score),
        ))
    return sorted(lines, key=lambda item: (item.y, item.x))


def _group_rows(lines: list[OCRLine], height: int) -> list[list[OCRLine]]:
    rows: list[list[OCRLine]] = []
    tolerance = max(9 / height, 0.008)
    for line in lines:
        if not rows or abs(line.y - sum(item.y for item in rows[-1]) / len(rows[-1])) > tolerance:
            rows.append([line])
        else:
            rows[-1].append(line)
    return [sorted(row, key=lambda item: item.x) for row in rows]


HEADER_LABELS = {
    "nama_kepala_keluarga": r"nama\s+kepala\s+keluarga",
    "alamat": r"alamat",
    "rt_rw": r"rt\s*/\s*rw|rtrw",
    "desa_kelurahan": r"desa\s*/\s*kelurahan|desa\s+kelurahan",
    "kecamatan": r"kecamatan",
    "kabupaten_kota": r"kabupaten\s*/\s*kota|kabupaten\s+kota",
    "kode_pos": r"kode\s+pos|kodepos",
    "provinsi": r"provinsi",
}


def _extract_labeled_values(lines: list[OCRLine]) -> dict[str, str]:
    label_regex = re.compile(
        "|".join(f"(?P<{key}>{pattern})" for key, pattern in HEADER_LABELS.items()),
        re.IGNORECASE,
    )
    values: dict[str, str] = {}
    # KK headers put several label/value pairs on the same horizontal line.
    # Split a row at every recognized label so the next field's label/value
    # cannot leak into the preceding field (the bug in the earlier parser).
    for row in _group_rows(lines, 1000):
        row_text = " ".join(line.text for line in row)
        matches = list(label_regex.finditer(row_text))
        for index, match in enumerate(matches):
            key = match.lastgroup
            if not key:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(row_text)
            value = row_text[match.end():end].strip(" \t:;|,.-")
            if value and key not in values:
                values[key] = re.sub(r"\s+", " ", value).strip()
    return values


def _extract_header(lines: list[OCRLine]) -> dict[str, str]:
    labeled = _extract_labeled_values(lines)
    kk_number = ""
    # Prefer a 16-digit value read close to the visible NO. KK label.
    for i, line in enumerate(lines):
        if "kk" in _norm(line.text) and any(word in _norm(line.text) for word in ("no", "nomor")):
            nearby = " ".join(item.text for item in lines if abs(item.y - line.y) < 0.035)
            match = re.search(r"(?:\d[\s.-]?){16}", nearby)
            if match:
                kk_number = re.sub(r"\D", "", match.group())[:16]
                break
    if not kk_number:
        for line in lines:
            digits = re.sub(r"\D", "", line.text)
            if len(digits) == 16 and line.y < 0.22:
                kk_number = digits
                break

    rt_rw = labeled.get("rt_rw", "")
    rt = rw = ""
    match = re.search(r"(\d{1,3})\s*[/.-]\s*(\d{1,3})", rt_rw)
    if match:
        rt, rw = match.groups()
    else:
        for line in lines:
            match = re.search(r"(\d{1,3})\s*[/.-]\s*(\d{1,3})", line.text)
            if match and line.y < 0.4:
                rt, rw = match.groups()
                break

    return {
        "nomor_kk": kk_number,
        "nama_kepala_keluarga": labeled.get("nama_kepala_keluarga", ""),
        "alamat": labeled.get("alamat", ""),
        "rt": rt,
        "rw": rw,
        "desa_kelurahan": labeled.get("desa_kelurahan", ""),
        "kecamatan": labeled.get("kecamatan", ""),
        "kabupaten_kota": labeled.get("kabupaten_kota", ""),
        "kode_pos": labeled.get("kode_pos", ""),
        "provinsi": labeled.get("provinsi", ""),
    }


def _header_row_y(rows: list[list[OCRLine]], keywords: tuple[str, ...]) -> float | None:
    for row in rows:
        text = _norm(" ".join(line.text for line in row))
        if sum(keyword in text for keyword in keywords) >= 3:
            return sum(line.y for line in row) / len(row)
    return None


def _table_rows(
    lines: list[OCRLine], rows: list[list[OCRLine]], header_y: float | None,
    lower_y: float | None, edges: tuple[float, ...],
) -> dict[int, list[str]]:
    if header_y is None:
        return {}
    bottom = lower_y if lower_y is not None and lower_y > header_y else 0.96
    anchors = []
    for line in lines:
        match = re.fullmatch(r"\s*(\d{1,2})\s*[.)]?\s*", line.text)
        if match and line.x < 0.035 and header_y < line.y < bottom:
            anchors.append((int(match.group(1)), line.y))
    row_positions: dict[int, float] = {}
    for number, y in sorted(anchors, key=lambda item: item[1]):
        if number not in row_positions or abs(row_positions[number] - y) > 0.01:
            row_positions[number] = y
    if not row_positions:
        body_rows = [row for row in rows if header_y < sum(item.y for item in row) / len(row) < bottom]
        row_positions = {
            index: sum(item.y for item in row) / len(row)
            for index, row in enumerate(body_rows, start=1)
        }

    parsed: dict[int, list[str]] = {}
    ordered_positions = sorted(row_positions.items(), key=lambda item: item[1])
    for index, (number, y) in enumerate(ordered_positions):
        previous_y = ordered_positions[index - 1][1] if index else header_y
        next_y = ordered_positions[index + 1][1] if index + 1 < len(ordered_positions) else bottom
        nearest_gap = min(y - previous_y, next_y - y)
        tolerance = min(0.012, max(0.004, nearest_gap * 0.45))
        band = [line for line in lines if abs(line.y - y) <= tolerance]
        cells = [""] * (len(edges) - 1)
        for line in sorted(band, key=lambda item: item.x):
            col = next((i for i in range(len(edges) - 1) if edges[i] <= line.x < edges[i + 1]), None)
            if col is not None and line.x >= 0.027:
                value = _clean_cell(line.text)
                if value:
                    cells[col] = (cells[col] + " " + value).strip()
        parsed[number] = cells
    return parsed


def _extract_members_inferred_rows(lines: list[OCRLine], image_height: int) -> list[dict[str, str]]:
    rows = _group_rows(lines, image_height)
    top_header_y = _header_row_y(rows, ("nama lengkap", "nik", "jenis kelamin", "tempat lahir", "tanggal lahir", "pendidikan"))
    bottom_header_y = _header_row_y(rows, ("status perkawinan", "status hubungan", "kewarganegaraan", "dokumen imigrasi", "ayah", "ibu"))
    # KK print layout has two aligned tables. Row numbers pair upper personal
    # data with lower marital/status/document/parent fields.
    top_edges = (0.0, 0.031, 0.228, 0.318, 0.378, 0.524, 0.576, 0.645, 0.822, 1.01)
    bottom_edges = (0.0, 0.032, 0.139, 0.251, 0.356, 0.483, 0.576, 0.775, 1.01)
    top = _table_rows(lines, rows, top_header_y, bottom_header_y, top_edges)
    bottom = _table_rows(lines, rows, bottom_header_y, None, bottom_edges)
    members = []
    for number in sorted(set(top) | set(bottom)):
        upper = top.get(number, [""] * 9)
        lower = bottom.get(number, [""] * 8)
        upper = [_clean_cell(value) for value in upper]
        lower = [_clean_cell(value) for value in lower]
        name = upper[1]
        nik_match = re.search(r"\d[\d .-]{10,18}\d", upper[2])
        nik = re.sub(r"\D", "", nik_match.group())[:16] if nik_match else ""
        if not nik and len(name) < 3:
            continue
        date_match = re.search(r"\b\d{1,2}[-/ ]\d{1,2}[-/ ]\d{2,4}\b", upper[5])
        members.append({
            "nik": nik,
            "nama_lengkap": name,
            "jenis_kelamin": upper[3],
            "tempat_lahir": upper[4],
            "tanggal_lahir": date_match.group() if date_match else upper[5],
            "agama": upper[6],
            "pendidikan": upper[7],
            "jenis_pekerjaan": upper[8],
            "status_perkawinan": lower[1],
            "status_hubungan_dalam_keluarga": lower[2],
            "kewarganegaraan": lower[3],
            "no_paspor": lower[4],
            "no_kitas_kitap": lower[5],
            "nama_ayah": lower[6],
            "nama_ibu": lower[7],
        })
    return members


def _candidate_positions(lines: list[OCRLine], predicate, min_y: float, max_y: float) -> list[float]:
    positions: list[float] = []
    for line in lines:
        if min_y < line.y < max_y and predicate(line):
            if not positions or min(abs(line.y - position) for position in positions) > 0.008:
                positions.append(line.y)
    return sorted(positions)


def _read_cells(lines: list[OCRLine], y: float, edges: tuple[float, ...], tolerance: float = 0.006) -> list[str]:
    cells = [""] * (len(edges) - 1)
    for line in sorted((item for item in lines if abs(item.y - y) <= tolerance), key=lambda item: item.x):
        col = next((i for i in range(len(edges) - 1) if edges[i] <= line.x < edges[i + 1]), None)
        if col is not None and line.x >= 0.027:
            value = _clean_cell(line.text)
            if value:
                cells[col] = (cells[col] + " " + value).strip()
    return cells


def _extract_members(lines: list[OCRLine], image_height: int) -> list[dict[str, str]]:
    """Read the two printed member tables and pair their rows by position."""
    rows = _group_rows(lines, image_height)
    top_header_y = _header_row_y(rows, ("nama lengkap", "nik", "jenis kelamin", "tempat lahir", "tanggal lahir", "pendidikan"))
    if top_header_y is None:
        return []

    # On this KK layout, the lower table begins at the first status/document
    # header. Its data rows repeat the same 1..10 sequence as the upper table.
    lower_header_lines = [
        line for line in lines
        if 0.44 < line.y < 0.61
        and any(word in _norm(line.text) for word in ("status", "dokumen imigrasi", "nama orang tua", "kewarganegaraan"))
    ]
    lower_header_y = min((line.y for line in lower_header_lines), default=0.53)

    top_edges = (0.0, 0.031, 0.228, 0.318, 0.378, 0.524, 0.576, 0.645, 0.822, 1.01)
    lower_edges = (0.0, 0.032, 0.139, 0.251, 0.356, 0.483, 0.576, 0.775, 1.01)
    top_min = top_header_y + 0.02
    top_max = lower_header_y - 0.02

    # Name rows are a reliable anchor even when the tiny printed row numbers
    # themselves are missed by OCR. Pure numbers/header labels are discarded.
    upper_positions = _candidate_positions(
        lines,
        lambda line: 0.035 <= line.x < 0.228
        and any(ch.isalpha() for ch in _clean_cell(line.text))
        and len(_clean_cell(line.text)) >= 4
        and _norm(_clean_cell(line.text)) not in {"nama lengkap", "no"},
        top_min,
        top_max,
    )
    if not upper_positions:
        upper_positions = _candidate_positions(
            lines,
            lambda line: 0.228 <= line.x < 0.318
            and len(re.sub(r"\D", "", line.text)) >= 12,
            top_min,
            top_max,
        )

    # Values in the first column of the lower table (e.g. KAWIN) anchor each
    # lower row; then row 1 is paired with upper row 1, row 2 with row 2, etc.
    lower_positions = _candidate_positions(
        lines,
        lambda line: 0.035 <= line.x < 0.139
        and any(ch.isalpha() for ch in _clean_cell(line.text))
        and len(_clean_cell(line.text)) >= 3,
        lower_header_y + 0.055,
        0.81,
    )

    members = []
    for index, upper_y in enumerate(upper_positions):
        upper = _read_cells(lines, upper_y, top_edges)
        lower = _read_cells(lines, lower_positions[index], lower_edges) if index < len(lower_positions) else [""] * 8
        upper = [_clean_cell(value) for value in upper]
        lower = [_clean_cell(value) for value in lower]
        name = upper[1]
        nik_match = re.search(r"\d[\d .-]{10,18}\d", upper[2])
        nik = re.sub(r"\D", "", nik_match.group())[:16] if nik_match else ""
        if not nik and len(name) < 3:
            continue
        marital = lower[1]
        marital_norm = _norm(marital)
        if "bel" in marital_norm and ("in" in marital_norm or "kawin" in marital_norm):
            marital = "BELUM KAWIN"
        elif "kawin" in marital_norm:
            marital = "KAWIN"
        relation = lower[2]
        relation_norm = _norm(relation)
        if "kepala" in relation_norm:
            relation = "KEPALA KELUARGA"
        elif "isteri" in relation_norm or "istri" in relation_norm:
            relation = "ISTERI"
        elif "anak" in relation_norm:
            relation = "ANAK"
        members.append({
            "nik": nik,
            "nama_lengkap": name,
            "jenis_kelamin": upper[3],
            "tempat_lahir": upper[4],
            "tanggal_lahir": upper[5],
            "agama": upper[6],
            "pendidikan": upper[7],
            "jenis_pekerjaan": upper[8],
            "status_perkawinan": marital,
            "status_hubungan_dalam_keluarga": relation,
            "kewarganegaraan": lower[3],
            "no_paspor": lower[4],
            "no_kitas_kitap": lower[5],
            "nama_ayah": lower[6],
            "nama_ibu": lower[7],
        })
    return members


def read_kk_image(image_bytes: bytes) -> dict[str, Any]:
    """OCR an uploaded KK and return best-effort editable form values."""
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        return {
            "identitas": {}, "anggota": [{}],
            "notice": "Gambar tidak terbaca sebagai format gambar. Periksa kembali file.",
            "raw_text": "",
        }

    try:
        lines = _read_lines(image)
    except Exception as exc:
        return {
            "identitas": {}, "anggota": [{}],
            "notice": f"OCR gagal dijalankan ({type(exc).__name__}). Silakan isi data secara manual.",
            "raw_text": "",
        }
    if not lines:
        return {
            "identitas": {}, "anggota": [{}],
            "notice": "Teks belum berhasil terbaca otomatis. Silakan isi atau koreksi data.",
            "raw_text": "",
        }
    identitas = _extract_header(lines)
    anggota = _extract_members(lines, image.shape[0]) or [{}]
    extracted = sum(bool(value) for value in identitas.values()) + sum(
        bool(value) for member in anggota for value in member.values()
    )
    return {
        "identitas": identitas,
        "anggota": anggota,
        "notice": f"OCR lokal menemukan sekitar {extracted} nilai. Periksa kembali karena hasil pembacaan bisa keliru.",
        "raw_text": "\n".join(line.text for line in lines),
    }
