from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
import tempfile

app = FastAPI()

# ✅ CORS settings for Lovable preview + live
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

# ✅ New route: Accepts direct file uploads
@app.post("/extract-transactions")
async def extract_transactions(file: UploadFile = File(...)):
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
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
