# Property OCR Pipeline — VSCode Project

## Stack
- **Backend**: FastAPI (Python)
- **OCR**: Sarvam Vision API (with chunking for >10 pages)
- **Structuring LLM**: Groq (llama-3.3-70b)
- **Frontend**: Vanilla HTML/CSS/JS (single file, no build step)
- **Preprocessing**: OpenCV + PIL (contrast, denoise, deskew)

## Project Structure
```
property_ocr/
├── backend/
│   ├── main.py                  # FastAPI app entry point
│   ├── routers/
│   │   └── pipeline.py          # /upload and /process endpoints
│   ├── services/
│   │   ├── preprocessor.py      # Image quality enhancement
│   │   ├── sarvam_ocr.py        # Sarvam API + chunking logic
│   │   ├── ocr_merger.py        # Merge chunked OCR outputs
│   │   ├── groq_structurer.py   # Groq LLM structuring
│   │   └── doc_classifier.py    # Detect doc type from filename/content
│   ├── schemas/
│   │   ├── sale_deed.py         # Pydantic schema for Sale Deed
│   │   └── ec.py                # Pydantic schema for EC
│   └── utils/
│       └── file_utils.py        # Path helpers, cleanup
├── frontend/
│   └── index.html               # Full UI (upload + results)
├── uploads/                     # Temp uploaded PDFs
├── outputs/
│   └── structured/              # Final structured JSONs
├── .env.example                 # API key template
├── requirements.txt
└── README.md
```

## Setup
```bash
# 1. Clone / extract zip
# 2. Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set API keys
cp .env.example .env
# Edit .env and add your keys

# 5. Run
uvicorn backend.main:app --reload --port 8000

# 6. Open browser
# http://localhost:8000
```

## API Keys needed
- `SARVAM_API_KEY` — from sarvam.ai dashboard
- `GROQ_API_KEY`   — from console.groq.com
