from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
import tempfile
import logging
import re
from decimal import Decimal, InvalidOperation

app = FastAPI()
logging.basicConfig(level=logging.INFO)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://eaba3391-227e-4abe-a519-84a02fedd2a7.lovableproject.com",
        "https://id-preview--eaba3391-227e-4abe-a519-84a02fedd2a7.lovable.app",
        "https://14d3c89d-ca06-45cc-9164-93a318796f46.lovableproject.com",
        "https://id-preview--14d3c89d-ca06-45cc-9164-93a318796f46.lovable.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONTHS = {"Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"}

def is_date_cell(s: str) -> bool:
    if not s: 
        return False
    t = s.strip()
    # e.g., "Jun 27", "Jul 2", "Jun 21 Opening Balance"
    parts = t.split()
    if len(parts) >= 2 and parts[0][:3].title() in MONTHS:
        # First two tokens look like a month and day number
        return re.match(r"^\d{1,2}$", parts[1]) is not None
    return False

def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

def parse_amount(s: str):
    s = clean(s).replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, TypeError):
        return None

TABLE_SETTINGS_CANDIDATES = [
    # Try text-based detection (works on gridless statements)
    dict(vertical_strategy="text", horizontal_strategy="text",
         snap_x_tolerance=3, snap_y_tolerance=3, text_tolerance=6),
    # Try line-based if there are ruling lines
    dict(vertical_strategy="lines", horizontal_strategy="lines"),
    # Mixed
    dict(vertical_strategy="lines", horizontal_strategy="text"),
    dict(vertical_strategy="text", horizontal_strategy="lines"),
]

def looks_like_header(row):
    if not row: 
        return False
    joined = " ".join([clean(c).lower() for c in row])
    return all(k in joined for k in ["date", "transactions"]) and (
        "withdrawn" in joined or "withdraw" in joined
    ) and ("deposit" in joined) and ("balance" in joined)

@app.post("/extract-transactions")
async def extract_transactions(file: UploadFile = File(...)):
    try:
        # Save temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file.flush()
            tmp_path = tmp_file.name

        all_transactions = []
        headers = None

        with pdfplumber.open(tmp_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                tables = []
                for ts in TABLE_SETTINGS_CANDIDATES:
                    try:
                        tables = page.extract_tables(table_settings=ts)
                        if tables:
                            break
                    except Exception as _:
                        continue

                if not tables:
                    logging.info(f"No tables found on page {page_num}")
                    continue

                # Pick the most "promising" table: prefer one with a header row we recognize
                chosen = None
                for tbl in tables:
                    if not tbl or not any(tbl):
                        continue
                    if looks_like_header(tbl[0]):
                        chosen = tbl
                        break
                if chosen is None:
                    # fallback: largest table by row count
                    chosen = max(tables, key=lambda t: len(t) if t else 0)

                if not chosen:
                    continue

                # Normalize rows to 5 columns if possible
                # Some cells may be None—coerce to empty strings
                norm = [[clean(c) for c in (row or [])] for row in chosen]

                # Find header row
                hdr_row_idx = None
                for i, row in enumerate(norm):
                    if looks_like_header(row):
                        hdr_row_idx = i
                        break

                if hdr_row_idx is None:
                    # Some PDFs render the header split across lines; try a heuristic:
                    # look for a row with at least 4 of the expected keys
                    for i, row in enumerate(norm[:5]):
                        joined = " ".join(row).lower()
                        score = sum(k in joined for k in ["date","transactions","withdraw","withdrawn","deposited","balance"])
                        if score >= 4:
                            hdr_row_idx = i
                            break

                data_rows = norm[hdr_row_idx+1:] if hdr_row_idx is not None else norm

                # Establish headers for response
                headers = headers or ["Date", "Transactions", "Withdrawn", "Deposited", "Balance"]

                # Parse into transactions; merge description continuations
                current = None
                for ridx, row in enumerate(data_rows, start=1):
                    # pad to 5 columns
                    row = (row + [""]*5)[:5]
                    date, desc, withdrawn, deposited, balance = row

                    # Skip boilerplate
                    junk = "continued on next page"
                    if junk in " ".join(row).lower():
                        continue

                    # Continuation line: no date, mostly description
                    if not is_date_cell(date) and desc:
                        if current:
                            # append line to description
                            current["description"] = clean(current["description"] + " " + desc)
                            # fill any amounts that might be split on next line (rare)
                            if not current.get("withdrawn"):
                                w = parse_amount(withdrawn)
                                if w is not None:
                                    current["withdrawn"] = str(w)
                            if not current.get("deposited"):
                                d = parse_amount(deposited)
                                if d is not None:
                                    current["deposited"] = str(d)
                            if not current.get("balance"):
                                b = parse_amount(balance)
                                if b is not None:
                                    current["balance"] = str(b)
                        continue

                    # New transaction line
                    if is_date_cell(date):
                        # Finish previous
                        if current:
                            all_transactions.append(current)

                        w = parse_amount(withdrawn)
                        d = parse_amount(deposited)
                        b = parse_amount(balance)

                        # Compute a signed "amount" field for convenience
                        amount = None
                        if w is not None and (d is None or w != 0):
                            amount = -w
                        elif d is not None:
                            amount = d

                        current = {
                            "date": date.strip(),
                            "description": desc.strip(),
                            "withdrawn": str(w) if w is not None else "",
                            "deposited": str(d) if d is not None else "",
                            "balance": str(b) if b is not None else "",
                            "amount": str(amount) if amount is not None else "",
                        }
                    else:
                        # Row with nothing usable
                        continue

                # flush last row for this page
                if current:
                    all_transactions.append(current)
                    current = None

        logging.info(f"📊 Total transactions extracted: {len(all_transactions)}")
        return {
            "headers": headers or ["Date", "Transactions", "Withdrawn", "Deposited", "Balance", "Amount"],
            "transactions": all_transactions
        }

    except Exception as e:
        logging.exception("Error extracting transactions")
        return {"error": str(e)}

