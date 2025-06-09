from fastapi import FastAPI
from pydantic import BaseModel
import pdfplumber
import requests
import tempfile
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://eaba3391-227e-4abe-a519-84a02fedd2a7.lovableproject.com"],
    allow_credentials=True,
    allow_methods=["*"],  # or ["POST"]
    allow_headers=["*"],
)

class PDFInput(BaseModel):
    url: str

@app.post("/extract-transactions")
def extract_transactions(data: PDFInput):
    try:
        response = requests.get(data.url)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            tmp_file.write(response.content)
            tmp_file.flush()

            transactions = []
            with pdfplumber.open(tmp_file.name) as pdf:
                for page in pdf.pages:
                    table = page.extract_table()
                    if table:
                        for row in table[1:]:  # Skip header
                            try:
                                date, description, amount = row[0], row[1], row[2]
                                transactions.append({
                                    "date": date.strip(),
                                    "description": description.strip(),
                                    "amount": amount.strip()
                                })
                            except Exception:
                                continue
        return {"transactions": transactions}
    except Exception as e:
        return {"error": str(e)}
