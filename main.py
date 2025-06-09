from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pdfplumber
import requests
import tempfile

app = FastAPI()

# ✅ Add both Lovable domains here
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://eaba3391-227e-4abe-a519-84a02fedd2a7.lovableproject.com",
        "https://id-preview--eaba3391-227e-4abe-a519-84a02fedd2a7.lovable.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ✅ CORS test route
@app.get("/test-cors")
def test_cors():
    return {"message": "✅ CORS is working!"}

# ✅ Health check for OPTIONS preflight requests
@app.options("/extract-transactions")
def preflight_check():
    return {"status": "ok"}

# ✅ Main extraction route
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
                        for row in table[1:]:
                            try:
                                date, description, amount = row[0], row[1], row[2]
                                transactions.append({
                                    "date": date.strip(),
                                    "description": description.strip(),
                                    "amount": amount.strip()
                                })
                            except:
                                continue
        return {"transactions": transactions}
    except Exception as e:
        return {"error": str(e)}
