from dotenv import load_dotenv
import os
load_dotenv()

from google import genai
import fitz
import json
import time
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("WARNING: GEMINI_API_KEY environment variable is not set!")
client = genai.Client(api_key=api_key)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODELS_TO_TRY = [
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite-001",
    "gemini-2.0-flash-001",
    "gemini-flash-lite-latest",
]


def extract_text(file_bytes):
    pdf = fitz.open(stream=file_bytes, filetype="pdf")
    text = ""
    for page in pdf:
        text += page.get_text()
    pages = pdf.page_count
    pdf.close()
    return text, pages


def analyze_with_gemini(text):
    prompt = f"""You are a legal document analyzer. Analyze the following legal document and respond ONLY with a valid JSON object. No extra text, no markdown, no backticks. Just pure JSON.

{{
  "summary": "2-3 sentence plain English summary of what this document is about",
  "risk_level": "High",
  "risk_reason": "One sentence explaining the risk level",
  "red_flags": [
    {{
      "title": "Short title of the issue",
      "description": "Plain English explanation of why this is a problem",
      "severity": "High",
      "suggestion": "Specific wording or change the person should propose to fix this clause"
    }}
  ],
  "clauses": [
    {{
      "name": "Clause name",
      "plain_english": "What this clause means in simple terms",
      "risk": "Low"
    }}
  ]
}}
Risk level must be exactly one of: Low, Medium, High
Severity must be exactly one of: High, Medium
Clause risk must be exactly one of: Low, Medium, High

Find ALL red flags and ALL major clauses. Be thorough.
For each red flag, give a practical negotiation suggestion — specific wording the person could propose to the other party to fix or soften that clause.

DOCUMENT:
{text[:8000]}"""

    last_error = None

    for model_name in MODELS_TO_TRY:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                response_text = response.text.strip()

                if "```" in response_text:
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]

                return json.loads(response_text.strip())

            except Exception as e:
                last_error = e
                print(f"Model {model_name} attempt {attempt + 1} failed: {e}")
                time.sleep(2)
                continue

    raise Exception(f"All models failed. Last error: {last_error}")


def chat_with_document(document_text, question, chat_history):
    history_text = ""
    for msg in chat_history:
        role = "User" if msg["role"] == "user" else "Assistant"
        history_text += f"{role}: {msg['content']}\n"

    prompt = f"""You are a legal assistant answering questions about a specific document. Only use information from the document below to answer. If the answer isn't in the document, say so clearly. Be concise and direct — 2-4 sentences max. Reference specific sections when possible.

DOCUMENT:
{document_text[:8000]}

CONVERSATION SO FAR:
{history_text}

NEW QUESTION: {question}

Answer the question based only on the document above."""

    last_error = None
    for model_name in MODELS_TO_TRY:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                return response.text.strip()
            except Exception as e:
                last_error = e
                print(f"Chat model {model_name} attempt {attempt + 1} failed: {e}")
                time.sleep(2)
                continue

    raise Exception(f"Chat failed. Last error: {last_error}")


class ChatRequest(BaseModel):
    document_text: str
    question: str
    chat_history: List[Dict[str, str]] = []


@app.get("/")
def home():
    return {"message": "LegalEase backend is running!"}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    contents = await file.read()
    text, pages = extract_text(contents)
    analysis = analyze_with_gemini(text)
    return {
        "filename": file.filename,
        "pages": pages,
        "text": text,
        "analysis": analysis
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    answer = chat_with_document(request.document_text, request.question, request.chat_history)
    return {"answer": answer}