from fastapi import FastAPI, HTTPException, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Optional
from pydantic import BaseModel
from math import ceil
import requests, uvicorn, json
from config import *

DATABASE_URL = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

class FAQ(Base):
    __tablename__ = "pertanyaan"
    id = Column(Integer, primary_key=True, index=True)
    pertanyaan = Column(Text, nullable=False)
    jawaban = Column(Text, nullable=False)

class AskInput(BaseModel):
    pertanyaan: str

Base.metadata.create_all(bind=engine)

# load cache
chat_memory = {}

# load model
chatbot = initiate_chatbot()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
def read_faqs(
    request: Request,
    q: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    base_query = db.query(FAQ)

    if q:
        base_query = base_query.filter(FAQ.pertanyaan.like(f"%{q}%"))

    total = base_query.count()
    faqs = base_query.order_by(FAQ.id.desc()).offset((page - 1) * limit).limit(limit).all()

    total_pages = ceil(total / limit)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "faqs": faqs,
        "query": q,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    })
@app.post("/add")
def add_faq(pertanyaan: str = Form(...), jawaban: str = Form(...), db: Session = Depends(get_db)):
    faq = FAQ(pertanyaan=pertanyaan, jawaban=jawaban)
    db.add(faq)
    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/edit/{faq_id}", response_class=HTMLResponse)
def edit_faq_form(request: Request, faq_id: int, q: Optional[str] = None, db: Session = Depends(get_db)):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ tidak ditemukan")
    return templates.TemplateResponse("edit.html", {"request": request, "faq": faq, "query": q})

@app.post("/edit/{faq_id}")
def edit_faq(
    faq_id: int,
    pertanyaan: str = Form(...),
    jawaban: str = Form(...),
    q: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ tidak ditemukan")
    faq.pertanyaan = pertanyaan
    faq.jawaban = jawaban
    db.commit()
    if q:
        return RedirectResponse(url=f"/?q={q}", status_code=303)
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete/{faq_id}")
def delete_faq(request: Request, faq_id: int, db: Session = Depends(get_db)):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ tidak ditemukan")
    db.delete(faq)
    db.commit()

    referer = request.headers.get("referer")
    return RedirectResponse(url=referer if referer else "/", status_code=303)

@app.get('/ask-form')
def ask_form(request: Request):
    return templates.TemplateResponse("test_model.html", {"request": request})

@app.post('/ask')
def ask(data: AskInput):
    try:
        query = data.pertanyaan
        answer = chatbot.search(query=query)[0][1]

        return {
            "status": "success",
            "message": "Pertanyaan berhasil diajukan",
            "pertanyaan": query,
            "jawaban": answer
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/update-model")
def update_model():
    global chatbot

    try:
        chatbot = initiate_chatbot()
        return {"message": "Chatbot berhasil diperbarui"}
    except Exception as e:
        return {"message": str(e)}

@app.post("/webhook")
async def webhook_post(request: Request):
    try:
        data = await request.json()
        print(f"Incoming webhook message: {json.dumps(data, indent=2)}")

        changes = data.get("entry", [{}])[0].get("changes", [{}])[0]
        value = changes.get("value", {})
        message_object = value.get("messages", [{}])[0]
        metadata = value.get("metadata", {})

    except Exception as e:
        print(f"Error parsing webhook payload structure: {e}")
        raise HTTPException(status_code=400, detail="Malformed payload")

    if message_object and message_object.get("type") == "text":
        business_phone_number_id = metadata.get("phone_number_id")
        user_message_text = message_object.get("text", {}).get("body")
        message_from = message_object.get("from")
        message_id = message_object.get("id")

        if not all([business_phone_number_id, user_message_text, message_from, message_id]):
            print("Error: Missing essential message data.")
            raise HTTPException(status_code=400, detail="Missing message data")

        print(f"User message: '{user_message_text}' from {message_from}")

        # get reply by bot
        reply = chatbot.search(user_message_text)[0][1]

        # Send reply
        graph_api_url = f"https://graph.facebook.com/v22.0/{business_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {GRAPH_API_TOKEN}",
            "Content-Type": "application/json",
        }

        payload_reply = {
            "messaging_product": "whatsapp",
            "to": message_from,
            "text": {"body": reply},
            "context": {"message_id": message_id},
        }

        try:
            response_reply = requests.post(graph_api_url, headers=headers, json=payload_reply)
            response_reply.raise_for_status()
            print(f"Reply sent successfully: {response_reply.json()}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending reply message: {e}")
            if e.response is not None:
                print(f"Response content: {e.response.content}")

        # Mark message as read
        if reply != "":
            payload_read = {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            }

            try:
                response_read = requests.post(graph_api_url, headers=headers, json=payload_read)
                response_read.raise_for_status()
                print(f"Message marked as read: {response_read.json()}")
            except requests.exceptions.RequestException as e:
                print(f"Error marking message as read: {e}")
                if e.response is not None:
                    print(f"Response content: {e.response.content}")

    return JSONResponse(content={"status": "success"}, status_code=200)

@app.route("/webhook", methods=["GET"])
def webhook_get():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    print(f"GET /webhook - Mode: {mode}, Token: {token}, Challenge: {challenge}")

    if mode and token:
        if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
            print("Webhook verified successfully!")
            return challenge, 200
        else:
            print("Webhook verification failed: Mode or token mismatch.")
            return jsonify({"status": "error", "message": "Verification token mismatch"}), 403
    else:
        print("Webhook verification failed: Missing mode or token.")
        return jsonify({"status": "error", "message": "Missing mode or token"}), 400

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
