from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
import tempfile
import logging

app = FastAPI()

# Logging
logging.basicConfig(level=logging.INFO)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://eaba3391-227e-4abe-a519-84a02fedd2a7.lovableproject.com",
        "https://id-preview--eaba3391-227e-4abe-a519-84a02fedd2a7.lovable.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/extract-transactions")
async def extract_transactions(file: UploadFile = File(...)):
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file.flush()
            tmp_path = tmp_file.name

        transactions = []

        with pdfplumber.open(tmp_path) as pdf:
            for page_number, page in enumerate(pdf.pages):
                table = page.extract_table()
                if table:
                    headers = table[0]
                    logging.info(f" Page {page_number + 1} Headers: {headers}")
                    for row_index, row in enumerate(table[1:], start=1):
                        logging.info(f"Row {row_index}: {row}")
                        if row and len(row) >= 3:
                            transactions.append({
                                "date": str(row[0]).strip(),
                                "description": str(row[1]).strip(),
                                "amount": str(row[2]).strip()
                            })
                        else:
                            logging.warning(f" Skipping row {row_index}: incomplete or empty")

        logging.info(f"📊 Total transactions extracted: {len(transactions)}")
        return {
            "headers": headers,
            "transactions": transactions
        }

    except Exception as e:
        logging.error(" Error: %s", str(e))
        return {"error": str(e)}

