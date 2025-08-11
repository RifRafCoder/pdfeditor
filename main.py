# main.py
from fastapi import FastAPI, File, UploadFile, Response, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
import tempfile
import logging
import re
from decimal import Decimal
import httpx
from typing import Optional

app = FastAPI()
logging.basicConfig(level=logging.INFO)

# --- CORS ---
ALLOWED_ORIGINS = [
    "https://eaba3391-227e-4abe-a519-84a02fedd2a7.lovableproject.com",
    "https://id-preview--eaba3391-227e-4abe-a519-84a02fedd2a7.lovable.app",
    "https://14d3c89d-ca06-45cc-9164-93a318796f46.lovableproject.com",
    "https://id-preview--14d3c89d-ca06-45cc-9164-93a318796f46.lovable.app",
    # add any new lovable preview domains here
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS + ["*"],  # loosen if needed during dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Health check ---
@app.get("/ping")
def ping():
    return {"ok": True}

# --- Helpers for extraction ---
MONTHS = {"Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"}

def clean(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()

def is_month(s: str) -> bool:
    s = clean(s)
    return s[:3].title() in MONTHS

def is_day(s: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}", clean(s)))

def parse_amt(s: str):
    s = clean(s).replace(",", "")
    s = re.sub(r"[^\d\.\-]", "", s)
    if s in ("", "-"):
        return None
    try:
        return Decimal(s)
    except Exception:
        return None

TABLE_SETTINGS_CANDIDATES = [
    dict(vertical_strategy="text", horizontal_strategy="text",
         snap_x_tolerance=3, snap_y_tolerance=3, text_tolerance=6),
    dict(vertical_strategy="text", horizontal_strategy="lines"),
    dict(vertical_strategy="lines", horizontal_strategy="text"),
    dict(vertical_strategy="lines", horizontal_strategy="lines"),
]

def extract_withdraw_deposit(cells):
    cand = []
    if len(cells) >= 2:
        wA, dA = parse_amt(cells[-2]), parse_amt(cells[-1])
        cand.append(("A", wA, dA))
    if len(cells) >= 3:
        wB, dB = parse_amt(cells[-3]), parse_amt(cells[-2])
        cand.append(("B", wB, dB))
    if not cand:
        return None, None
    best = max(cand, key=lambda x: ((x[1] is not None) + (x[2] is not None), 1 if x[0]=="A" else 0))
    return best[1], best[2]

# --- PDF extraction endpoint (yours, kept) ---
@app.post("/extract-transactions")
async def extract_transactions(file: UploadFile = File(...)):
    try:
        if file.content_type != "application/pdf":
            # Some browsers don’t set content_type; we’ll allow anyway
            logging.info(f"Incoming content_type: {file.content_type}")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail="Empty file")
            tmp_file.write(content)
            tmp_file.flush()
            tmp_path = tmp_file.name

        transactions = []
        headers = ["Date", "Description", "Withdrawn", "Deposited", "Amount"]

        with pdfplumber.open(tmp_path) as pdf:
            total_rows_seen = 0
            for page_num, page in enumerate(pdf.pages, start=1):
                chosen = None
                for ts in TABLE_SETTINGS_CANDIDATES:
                    try:
                        tables = page.extract_tables(table_settings=ts)
                        if tables and len(tables[0]) > 0:
                            chosen = tables[0]
                            break
                    except Exception as e:
                        logging.debug(f"Table parse attempt failed: {e}")
                        continue

                if not chosen:
                    logging.info(f"[Pg {page_num}] No tables found")
                    continue

                total_rows_seen += len(chosen)
                logging.info(f"[Pg {page_num}] Rows detected: {len(chosen)}")

                current = None
                for idx, row in enumerate(chosen):
                    cells = [clean(c) for c in (row or [])]
                    if not any(cells):
                        continue

                    if idx == 0:
                        joined = " ".join(cells).lower()
                        if ("transactions" in joined) or ("withdrawn" in joined) or ("deposited" in joined):
                            continue

                    first = cells[0]
                    second = cells[1] if len(cells) > 1 else ""

                    date = None
                    rest = None
                    if is_month(first) and is_day(second):
                        date = f"{first} {second}"
                        rest = cells[2:]
                    elif re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}$", first):
                        date = first
                        rest = cells[1:]

                    if date:
                        if current:
                            transactions.append(current)

                        if rest is None:
                            desc_parts = []
                            w = d = None
                        else:
                            desc_parts = rest[:-3] if len(rest) >= 3 else rest
                            w, d = extract_withdraw_deposit(rest) if len(rest) >= 2 else (None, None)

                        description = " ".join([c for c in desc_parts if c]).strip()
                        amount = None
                        if w is not None and (d is None or w != 0):
                            amount = -w
                        elif d is not None:
                            amount = d

                        current = {
                            "date": date,
                            "description": description,
                            "withdrawn": str(w) if w is not None else "",
                            "deposited": str(d) if d is not None else "",
                            "amount": str(amount) if amount is not None else "",
                        }
                    else:
                        if not current:
                            continue
                        cont_desc = " ".join([c for c in cells[:-3]]) if len(cells) >= 3 else " ".join(cells)
                        current["description"] = clean(f'{current["description"]} {cont_desc}'.strip())

                        if len(cells) >= 2:
                            w_cont, d_cont = extract_withdraw_deposit(cells)
                            if not current["withdrawn"] and w_cont is not None:
                                current["withdrawn"] = str(w_cont)
                                current["amount"] = str(-w_cont)
                            if not current["deposited"] and d_cont is not None:
                                current["deposited"] = str(d_cont)
                                current["amount"] = str(d_cont)

                if current:
                    transactions.append(current)
                    current = None

        logging.info(f"📊 Total table rows seen (all pages): {total_rows_seen}")
        logging.info(f"📊 Total transactions extracted: {len(transactions)}")

        return {"headers": headers, "transactions": transactions}

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error extracting transactions")
        return {"error": str(e)}

# --- PDF proxy for canvas preview (use in Lovable) ---
@app.get("/pdf-proxy")
async def pdf_proxy(
    src: str = Query(..., description="Public or signed URL to the PDF"),
    filename: Optional[str] = Query("document.pdf")
):
    """
    Fetches a PDF from `src` and returns raw bytes with friendly headers.
    Use this URL in your Lovable PDF.js loader:
      /pdf-proxy?src=<encoded_pdf_url>
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            # If your storage needs auth, add headers here:
            # headers = {"Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_KEY']}"}
            r = await client.get(src)  # , headers=headers
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"Upstream error: {r.status_code}")

        headers = {
            "Content-Type": "application/pdf",
            "Access-Control-Allow-Origin": "*",
            "Accept-Ranges": "bytes",  # helps PDF.js; also okay if client disables range
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-store",
        }
        return Response(content=r.content, headers=headers, media_type="application/pdf")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Proxy network error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Proxy failed: {e}")

