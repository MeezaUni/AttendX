"""Timetable extraction from CSV / XLSX / PDF / images into an editable preview.

Nothing is saved here: the administrator reviews (and edits) the rows, then commits them.
Values that cannot be read are left EMPTY and flagged - course codes and times are never
invented. Supported layouts:

* long format - one row per class with headers such as ``day, period, start, end, course_code,
  course_name, section`` (CSV/XLSX templates in docs/samples/);
* grid format - weekdays down the first column, periods (numbers and/or time ranges) across the
  header row, course codes (optionally followed by names) or BREAK/LUNCH in the cells.

PDFs: text tables via pdfplumber; pages without a text layer are rendered and OCR'd.
Images (and scanned PDFs): RapidOCR (ONNX, runs locally) then a row/column reconstruction.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass, field
from typing import Any

WEEKDAY_NAMES = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}  # fmt: skip
BREAK_WORDS = ("break", "lunch", "recess", "interval", "free")
CODE_RE = re.compile(r"\b([A-Z]{2,5})\s?-?\s?(\d{3,4}[A-Z]?)\b")
TIME_RE = re.compile(r"(\d{1,2})\s*[:.]\s*(\d{2})\s*([AaPp][Mm])?")
RANGE_RE = re.compile(
    r"(\d{1,2}\s*[:.]\s*\d{2}\s*(?:[AaPp][Mm])?)\s*(?:-|–|—|to)\s*(\d{1,2}\s*[:.]\s*\d{2}\s*(?:[AaPp][Mm])?)"
)
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}

HEADER_SYNONYMS = {
    "weekday": ("day", "weekday", "day of week"),
    "period": ("period", "period no", "period number", "slot", "hour", "no"),
    "start": ("start", "start time", "from", "begins"),
    "end": ("end", "end time", "to", "ends"),
    "course_code": ("course code", "course_code", "code", "subject code", "course"),
    "course_name": ("course name", "course_name", "name", "subject", "subject name", "title"),
    "section": ("section", "class", "class section", "batch"),
    "is_break": ("break", "is break", "is_break", "type"),
    "faculty": ("faculty", "teacher", "instructor", "lecturer"),
    "room": ("room", "venue", "location"),
}

MAX_ROWS = 400


@dataclass
class ImportRow:
    weekday: int | None = None
    period: int | None = None
    start: str | None = None
    end: str | None = None
    course_code: str | None = None
    course_name: str | None = None
    section: str | None = None
    faculty: str | None = None
    room: str | None = None
    is_break: bool = False
    source: str = ""
    flags: list[str] = field(default_factory=list)


@dataclass
class ImportPreview:
    kind: str
    layout: str
    rows: list[ImportRow]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "layout": self.layout,
            "rows": [asdict(r) for r in self.rows],
            "warnings": self.warnings,
        }


class ImportError_(ValueError):
    pass


# ------------------------------------------------------------------ cell parsers


def norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s if s is not None else "")).strip()


def parse_weekday(s: str) -> int | None:
    key = re.sub(r"[^a-z]", "", s.lower())
    return WEEKDAY_NAMES.get(key)


def parse_time(s: str) -> tuple[str | None, str | None]:
    """'8:50', '08.50', '1:30 PM' -> ('HH:MM', flag). Hours 1-6 without AM/PM are ambiguous and
    returned as-is with a flag (never silently converted)."""
    m = TIME_RE.search(s or "")
    if not m:
        return None, None
    h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    flag = None
    if ampm:
        if h < 1 or h > 12:
            return None, f"invalid time '{s}'"
        h = h % 12 + (12 if ampm.lower() == "pm" else 0)
    elif 1 <= h <= 6:
        flag = f"time '{m.group(0)}' has no AM/PM; check whether it is afternoon"
    if h > 23 or mi > 59:
        return None, f"invalid time '{s}'"
    return f"{h:02d}:{mi:02d}", flag


def parse_period(s: str) -> int | None:
    t = norm(s).lower()
    m = re.search(r"(?:period|p|slot|hour)?\s*[-#.]?\s*(\d{1,2})\b", t)
    if m and not TIME_RE.fullmatch(t):
        n = int(m.group(1))
        if 1 <= n <= 12:
            return n
    word = re.sub(r"[^a-z]", "", t.replace("period", "").replace("slot", ""))
    return ROMAN.get(word)


def parse_course(cell: str) -> tuple[str | None, str | None, list[str]]:
    """Cell text -> (code, name, flags). Never guesses a code that is not literally present."""
    text = norm(cell)
    if not text:
        return None, None, []
    codes = [f"{a}{b}" for a, b in CODE_RE.findall(text.upper())]
    uniq = list(dict.fromkeys(codes))
    if not uniq:
        return None, text, [f"no course code found in '{text}'"]
    flags = []
    if len(uniq) > 1:
        flags.append(f"several course codes in one cell ({', '.join(uniq)}); first used")
    m = CODE_RE.search(text.upper())
    name = norm(text[: m.start()] + " " + text[m.end() :]) if m else ""
    name = re.sub(r"^[\s\-–:/()]+|[\s\-–:/()]+$", "", name)
    return uniq[0], (name or None), flags


def is_break_text(s: str) -> bool:
    t = norm(s).lower()
    return any(w == t or t.startswith(w) or f" {w}" in f" {t}" for w in BREAK_WORDS) and not (
        CODE_RE.search(s.upper())
    )


# ------------------------------------------------------------------ layout interpreters


def _match_header(cell: str) -> str | None:
    c = norm(cell).lower().replace("_", " ")
    for key, syns in HEADER_SYNONYMS.items():
        if c in syns:
            return key
    return None


def interpret_long(grid: list[list[str]], header_i: int) -> list[ImportRow]:
    cols: dict[str, int] = {}
    for j, cell in enumerate(grid[header_i]):
        key = _match_header(cell)
        if key and key not in cols:
            cols[key] = j
    rows = []
    for raw in grid[header_i + 1 :]:
        if not any(norm(c) for c in raw):
            continue

        def get(key: str, raw: list[str] = raw) -> str:
            j = cols.get(key)
            return norm(raw[j]) if j is not None and j < len(raw) else ""

        r = ImportRow(source=" | ".join(norm(c) for c in raw if norm(c)))
        day = get("weekday")
        r.weekday = parse_weekday(day)
        if r.weekday is None:
            r.flags.append(f"unrecognised weekday '{day}'" if day else "weekday missing")
        per = get("period")
        r.period = parse_period(per) if per else None
        if r.period is None:
            r.flags.append(f"unrecognised period '{per}'" if per else "period missing")
        for key in ("start", "end"):
            val, flag = parse_time(get(key))
            setattr(r, key, val)
            if flag:
                r.flags.append(flag)
        brk = get("is_break").lower()
        code_cell = get("course_code")
        r.is_break = brk in ("1", "true", "yes", "y", "break", "lunch") or (
            bool(code_cell) and is_break_text(code_cell)
        )
        if not r.is_break:
            code, name, flags = parse_course(code_cell)
            r.course_code = code
            r.course_name = get("course_name") or name
            r.flags += flags
            if not code_cell:
                r.flags.append("course code missing")
        r.section = get("section") or None
        r.faculty = get("faculty") or None
        r.room = get("room") or None
        rows.append(r)
    return rows


def _header_score(row: list[str]) -> int:
    score = 0
    for c in row[1:]:
        t = norm(c)
        if not t:
            continue
        if RANGE_RE.search(t) or parse_period(t) is not None:
            score += 1
    return score


def interpret_grid(grid: list[list[str]]) -> tuple[list[ImportRow], list[str]]:
    warnings: list[str] = []
    header_i = max(range(min(len(grid), 10)), key=lambda i: _header_score(grid[i]), default=0)
    if not grid or _header_score(grid[header_i]) == 0:
        raise ImportError_(
            "could not find a header row with period numbers or time ranges; "
            "use the long CSV/XLSX template or the manual editor"
        )
    header = grid[header_i]
    # some timetables put period numbers and times in two consecutive header rows
    times_row = None
    if header_i + 1 < len(grid) and parse_weekday(norm(grid[header_i + 1][0])) is None:
        if sum(bool(RANGE_RE.search(norm(c))) for c in grid[header_i + 1]) >= 2:
            times_row = grid[header_i + 1]
    columns: list[dict[str, Any]] = []
    seq = 0
    for j in range(1, len(header)):
        h = norm(header[j])
        t = norm(times_row[j]) if times_row and j < len(times_row) else ""
        rng = RANGE_RE.search(f"{h} {t}")
        hdr_no_time = RANGE_RE.sub("", h)
        per = parse_period(hdr_no_time) if hdr_no_time.strip() else None
        brk = is_break_text(h) or is_break_text(t)
        if not (rng or per or brk):
            continue
        col: dict[str, Any] = {"j": j, "period": per, "start": None, "end": None, "flags": []}
        if rng:
            for key, g in (("start", 1), ("end", 2)):
                val, flag = parse_time(rng.group(g))
                col[key] = val
                if flag:
                    col["flags"].append(flag)
        col["break"] = brk
        if not brk:
            seq += 1
            if per is None:
                col["flags"].append(
                    f"period number not stated in header '{h}'; numbered {seq} by position"
                )
                col["period"] = seq
        columns.append(col)
    rows: list[ImportRow] = []
    for raw in grid[header_i + 1 :]:
        if not raw:
            continue
        day = parse_weekday(norm(raw[0]))
        if day is None:
            if any(norm(c) for c in raw[1:]) and norm(raw[0]):
                warnings.append(f"row '{norm(raw[0])}' skipped: first cell is not a weekday")
            continue
        for col in columns:
            cell = norm(raw[col["j"]]) if col["j"] < len(raw) else ""
            if col["break"]:
                continue  # break columns: shown as gaps, no attendance
            if not cell:
                continue
            r = ImportRow(
                weekday=day,
                period=col["period"],
                start=col["start"],
                end=col["end"],
                source=cell,
                flags=list(col["flags"]),
            )
            if is_break_text(cell):
                r.is_break = True
            else:
                r.course_code, r.course_name, flags = parse_course(cell)
                r.flags += flags
            if r.start is None and not r.is_break:
                r.flags.append("no time in header; the period's default times will be used")
            rows.append(r)
    return rows, warnings


def interpret(grid: list[list[str]], kind: str) -> ImportPreview:
    grid = [[norm(c) for c in row] for row in grid if row is not None][: MAX_ROWS + 20]
    for i, row in enumerate(grid[:10]):
        keys = {_match_header(c) for c in row}
        if "weekday" in keys and ("period" in keys or "start" in keys):
            rows = interpret_long(grid, i)
            return ImportPreview(kind, "long", rows[:MAX_ROWS])
    rows, warnings = interpret_grid(grid)
    return ImportPreview(kind, "grid", rows[:MAX_ROWS], warnings)


# ------------------------------------------------------------------ file readers


def grid_from_csv(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def grid_from_xlsx(data: bytes) -> list[list[str]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    grid = []
    for row in ws.iter_rows(values_only=True):
        cells = []
        for v in row:
            if hasattr(v, "strftime") and not hasattr(v, "year"):
                v = v.strftime("%H:%M")
            cells.append("" if v is None else str(v))
        grid.append(cells)
        if len(grid) > MAX_ROWS + 20:
            break
    wb.close()
    return grid


def grid_from_ocr(items: list[tuple[list[list[float]], str, float]]) -> tuple[list[list[str]], list[str]]:
    """Rebuild a table from OCR boxes: cluster rows by y, columns by the header row's x."""
    warnings = []
    if not items:
        raise ImportError_("no text was recognised in the image")
    boxes = []
    for pts, text, score in items:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append(
            {"x0": min(xs), "x1": max(xs), "cx": sum(xs) / 4, "cy": sum(ys) / 4,
             "h": max(ys) - min(ys), "text": text, "score": score}
        )  # fmt: skip
    low = [b["text"] for b in boxes if b["score"] < 0.8]
    if low:
        warnings.append(f"{len(low)} text fragments were recognised with low confidence")
    hmed = sorted(b["h"] for b in boxes)[len(boxes) // 2] or 10
    boxes.sort(key=lambda b: b["cy"])
    rows: list[list[dict[str, Any]]] = []
    for b in boxes:
        if rows and abs(b["cy"] - sum(x["cy"] for x in rows[-1]) / len(rows[-1])) < 0.6 * hmed:
            rows[-1].append(b)
        else:
            rows.append([b])
    for r in rows:
        r.sort(key=lambda b: b["cx"])
    header = max(rows[:10], key=lambda r: _header_score(["", *[b["text"] for b in r]]))
    # column anchors come only from period / time / break headers; anything left of the first
    # anchor (e.g. "Day" and the weekday names) is the row-label column
    slots = [
        b for b in header
        if RANGE_RE.search(b["text"]) or parse_period(b["text"]) is not None or is_break_text(b["text"])
    ]  # fmt: skip
    if not slots:
        raise ImportError_("could not find period or time headers in the image")
    anchors = [b["cx"] for b in slots]
    boundary = min(b["x0"] for b in slots) - 0.25 * (slots[0]["x1"] - slots[0]["x0"])
    grid = []
    for r in rows:
        cells = [""] * (len(anchors) + 1)
        for b in r:
            if b["cx"] < boundary:
                j = 0
            else:
                j = 1 + min(range(len(anchors)), key=lambda k: abs(anchors[k] - b["cx"]))
            cells[j] = norm(f"{cells[j]} {b['text']}")
        grid.append(cells)
    return grid, warnings


_ocr_engine: Any = None


def ocr_image(rgb: Any) -> list[tuple[list[list[float]], str, float]]:
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    result, _ = _ocr_engine(rgb)
    return [(r[0], r[1], float(r[2])) for r in (result or [])]


def preview_upload(filename: str, data: bytes) -> ImportPreview:
    name = filename.lower()
    if name.endswith(".csv"):
        return interpret(grid_from_csv(data), "csv")
    if name.endswith((".xlsx", ".xlsm")):
        if not data.startswith(b"PK"):
            raise ImportError_("file is not a valid XLSX workbook")
        return interpret(grid_from_xlsx(data), "xlsx")
    if name.endswith(".pdf"):
        if not data.startswith(b"%PDF"):
            raise ImportError_("file is not a valid PDF")
        return preview_pdf(data)
    if name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        from attendx.face.engine import decode_image

        rgb = decode_image(data, max_side=3000)
        grid, warnings = grid_from_ocr(ocr_image(rgb))
        p = interpret(grid, "image")
        p.warnings = ["extracted with OCR: check every value", *warnings, *p.warnings]
        return p
    raise ImportError_("unsupported file type (use CSV, XLSX, PDF, PNG or JPG)")


def preview_pdf(data: bytes) -> ImportPreview:
    import numpy as np
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if len(pdf.pages) > 10:
            raise ImportError_("PDF has more than 10 pages")
        best: list[list[str]] = []
        for page in pdf.pages:
            for table in page.extract_tables():
                if len(table) * max((len(r) for r in table), default=0) > len(best) * max(
                    (len(r) for r in best), default=0
                ):
                    best = [[c or "" for c in row] for row in table]
        if best:
            p = interpret(best, "pdf")
            p.warnings.insert(0, "extracted from the PDF's table structure")
            return p
        text = "\n".join(page.extract_text(layout=True) or "" for page in pdf.pages)
        if text.strip():
            grid = [re.split(r"\s{2,}|\t", line.strip()) for line in text.splitlines() if line.strip()]
            p = interpret(grid, "pdf")
            p.warnings.insert(0, "no table structure found; columns were split on spacing")
            return p
        page = pdf.pages[0]
        img = page.to_image(resolution=200).original.convert("RGB")
        grid, warnings = grid_from_ocr(ocr_image(np.asarray(img)))
        p = interpret(grid, "pdf-ocr")
        p.warnings = ["scanned PDF: extracted with OCR, check every value", *warnings, *p.warnings]
        return p
