import io

import numpy as np
import pytest

from attendx.services.timetable_import import (
    ImportError_,
    parse_course,
    parse_period,
    parse_time,
    preview_upload,
)
from tests.conftest import make_section_course

LONG_CSV = b"""day,period,start,end,course_code,course_name,section
Monday,1,08:50,09:45,DL3101,Deep Learning,CSE-5A
Monday,2,09:45,10:40,CV3102,Computer Vision,CSE-5A
Monday,3,,,LUNCH,,CSE-5A
Tuesday,P1,8:50,9:45,Data Structures,,CSE-5A
Funday,1,08:50,09:45,DB3103,Databases,CSE-5A
"""

GRID_CSV = b"""Day,1 (08:50-09:45),2 (09:45-10:40),Break (10:40-10:55),3 (10:55-11:50)
Monday,DL3101 Deep Learning,CV3102,,MA3104 Statistics
Tuesday,CV3102,BREAK,,DL3101
"""


def test_cell_parsers():
    assert parse_time("8:50") == ("08:50", None)
    assert parse_time("1:30 PM") == ("13:30", None)
    t, flag = parse_time("1:30")
    assert t == "01:30" and "AM/PM" in flag  # never silently assumed
    assert parse_period("Period 3") == 3 and parse_period("P2") == 2 and parse_period("IV") == 4
    assert parse_course("DL 3101 - Deep Learning") == ("DL3101", "Deep Learning", [])
    code, name, flags = parse_course("Data Structures")
    assert code is None and flags  # no code invented


def test_long_csv():
    p = preview_upload("tt.csv", LONG_CSV)
    assert p.layout == "long" and len(p.rows) == 5
    r0 = p.rows[0]
    assert (r0.weekday, r0.period, r0.start, r0.end, r0.course_code, r0.course_name, r0.section) == (
        0, 1, "08:50", "09:45", "DL3101", "Deep Learning", "CSE-5A")  # fmt: skip
    assert p.rows[2].is_break
    assert p.rows[3].course_code is None and any("no course code" in f for f in p.rows[3].flags)
    assert p.rows[4].weekday is None and any("weekday" in f for f in p.rows[4].flags)


def test_grid_csv():
    p = preview_upload("grid.csv", GRID_CSV)
    assert p.layout == "grid"
    by = {(r.weekday, r.period): r for r in p.rows}
    assert by[(0, 1)].course_code == "DL3101" and by[(0, 1)].start == "08:50"
    assert by[(0, 3)].course_code == "MA3104" and by[(0, 3)].start == "10:55"
    assert by[(1, 2)].is_break
    assert not any(r.course_code is None and not r.is_break for r in p.rows)


def test_xlsx():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in GRID_CSV.decode().splitlines():
        ws.append(row.split(","))
    buf = io.BytesIO()
    wb.save(buf)
    p = preview_upload("tt.xlsx", buf.getvalue())
    assert p.kind == "xlsx" and len(p.rows) == 6


def _pdf(lines: list[list[tuple[float, str]]]) -> bytes:
    """Minimal single-page PDF with text placed at x positions (no external library)."""
    ops = ["BT /F1 10 Tf"]
    y = 750
    for row in lines:
        for x, text in row:
            ops.append(f"1 0 0 1 {x} {y} Tm ({text}) Tj")
        y -= 20
    ops.append("ET")
    stream = "\n".join(ops).encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    return out


def test_text_pdf():
    cols = [40, 140, 260, 380]
    rows = [
        ["Day", "1 08:50-09:45", "2 09:45-10:40", "3 10:55-11:50"],
        ["Monday", "DL3101", "CV3102", "MA3104"],
        ["Tuesday", "CV3102", "DL3101", "BREAK"],
    ]
    pdf = _pdf([[(x, t) for x, t in zip(cols, r, strict=True)] for r in rows])
    p = preview_upload("tt.pdf", pdf)
    by = {(r.weekday, r.period): r for r in p.rows}
    assert by[(0, 1)].course_code == "DL3101" and by[(0, 3)].course_code == "MA3104"
    assert by[(1, 3)].is_break


@pytest.mark.slow
def test_image_ocr():
    import cv2

    img = np.full((360, 1100, 3), 255, np.uint8)
    rows = [
        ["Day", "1 08:50-09:45", "2 09:45-10:40", "3 10:55-11:50"],
        ["Monday", "DL3101", "CV3102", "MA3104"],
        ["Tuesday", "CV3102", "DL3101", "BREAK"],
    ]
    for i, r in enumerate(rows):
        for j, t in enumerate(r):
            cv2.putText(img, t, (30 + j * 260, 80 + i * 100), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", img)
    p = preview_upload("tt.png", buf.tobytes())
    assert p.kind == "image" and "OCR" in p.warnings[0]
    codes = {(r.weekday, r.period): r.course_code for r in p.rows}
    assert codes.get((0, 1)) == "DL3101" and codes.get((0, 2)) == "CV3102"


def test_rejects_bad_files():
    with pytest.raises(ImportError_):
        preview_upload("x.exe", b"MZ")
    with pytest.raises(ImportError_):
        preview_upload("x.pdf", b"not a pdf")
    with pytest.raises(ImportError_):
        preview_upload("x.csv", b"just,some\nrandom,words\n")


def test_preview_and_commit_endpoints(admin, db):
    from attendx.models import Course, TimetableEntry

    sid, _ = make_section_course(admin)
    r = admin.post("/api/admin/timetable/import/preview", files={"file": ("tt.csv", GRID_CSV, "text/csv")})
    assert r.status_code == 200
    rows = r.json()["rows"]
    # nothing saved by preview
    assert db.query(TimetableEntry).count() == 0
    # commit fails while a new course has no name (CV3102 has none in the cells)
    bad = admin.post("/api/admin/timetable/import/commit", json={"rows": rows, "default_section_id": sid})
    assert bad.status_code == 422 and "needs a course name" in str(bad.json())
    for row in rows:
        if row["course_code"] == "CV3102":
            row["course_name"] = "Computer Vision"  # admin edits the preview
    ok = admin.post("/api/admin/timetable/import/commit", json={"rows": rows, "default_section_id": sid})
    assert ok.status_code == 200, ok.text
    assert ok.json()["saved"] == len(rows)
    assert {c.code for c in db.query(Course)} == {"DL3101", "CV3102", "MA3104"}
    e = db.query(TimetableEntry).filter_by(weekday=0, period_number=3).one()
    assert e.start_time is None  # header time equals the period default: no override stored
    missing = admin.post("/api/admin/timetable/import/commit",
                         json={"rows": [{"weekday": 0, "period": 1, "course_code": None}], "default_section_id": sid})  # fmt: skip
    assert missing.status_code == 422
