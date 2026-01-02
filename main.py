from fastapi import FastAPI, HTTPException, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, Text, String, DateTime, text, Enum
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from typing import Optional
from math import ceil
import requests
import uvicorn
import logging
from config import * # Pastikan file config.py ada isinya (DB creds & API Key)

# --- KONFIGURASI DATABASE ---
DATABASE_URL = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- DEFINISI MODEL TABEL ---

class FAQ(Base):
    __tablename__ = "pertanyaan"
    id = Column(Integer, primary_key=True, index=True)
    pertanyaan = Column(Text, nullable=False)
    jawaban = Column(Text, nullable=False)

class FAQPending(Base):
    __tablename__ = "pertanyaan_pending"
    id = Column(Integer, primary_key=True, index=True)
    nomor_wa = Column(String(50), nullable=False)
    pertanyaan = Column(Text, nullable=False)
    message_id = Column(String(255), nullable=True)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, index=True)
    nomor_wa = Column(String(50), nullable=False, index=True)
    role = Column(String(20), nullable=False) # 'user' atau 'assistant'
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

# --- INISIALISASI APP ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")
logging.basicConfig(level=logging.INFO)

# FITUR UTAMA: Membuat tabel otomatis jika belum ada
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- ROUTES DASHBOARD FAQ (CRUD) ---

@app.get("/", response_class=HTMLResponse)
def read_faqs(request: Request, q: Optional[str] = None, page: int = 1, limit: int = 50, db: Session = Depends(get_db)):
    base_query = db.query(FAQ)
    if q:
        base_query = base_query.filter(FAQ.pertanyaan.like(f"%{q}%"))
    
    total = base_query.count()
    faqs = base_query.order_by(FAQ.id.desc()).offset((page - 1) * limit).limit(limit).all()
    
    return templates.TemplateResponse("index.html", {
        "request": request, "faqs": faqs, "query": q,
        "total": total, "page": page, "limit": limit,
        "total_pages": ceil(total / limit),
        "has_next": page < ceil(total / limit), "has_prev": page > 1,
    })

@app.post("/add")
def add_faq(pertanyaan: str = Form(...), jawaban: str = Form(...), db: Session = Depends(get_db)):
    faq = FAQ(pertanyaan=pertanyaan, jawaban=jawaban)
    db.add(faq)
    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/edit/{faq_id}", response_class=HTMLResponse)
def edit_faq_form(request: Request, faq_id: int, db: Session = Depends(get_db)):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq: raise HTTPException(status_code=404, detail="FAQ not found")
    return templates.TemplateResponse("edit.html", {"request": request, "faq": faq})

@app.post("/edit/{faq_id}")
def edit_faq(faq_id: int, pertanyaan: str = Form(...), jawaban: str = Form(...), db: Session = Depends(get_db)):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if faq:
        faq.pertanyaan = pertanyaan
        faq.jawaban = jawaban
        db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete/{faq_id}")
def delete_faq(faq_id: int, db: Session = Depends(get_db)):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if faq:
        db.delete(faq)
        db.commit()
    return RedirectResponse(url="/", status_code=303)

# --- ROUTES BARU: MANAJEMEN PERTANYAAN PENDING & BALAS CHAT ---

@app.get("/pending", response_class=HTMLResponse)
def view_pending(request: Request, db: Session = Depends(get_db)):
    # Ambil pertanyaan yang statusnya masih 'pending'
    pending_list = db.query(FAQPending).filter(FAQPending.status == "pending").order_by(FAQPending.created_at.desc()).all()
    return templates.TemplateResponse("pending.html", {"request": request, "pending_list": pending_list})

@app.post("/reply-pending/{id}")
def reply_pending(id: int, jawaban: str = Form(...), save_to_faq: Optional[str] = Form(None), db: Session = Depends(get_db)):
    # Ambil data pending
    pending_item = db.query(FAQPending).filter(FAQPending.id == id).first()
    if not pending_item:
        raise HTTPException(status_code=404, detail="Data tidak ditemukan")

    # Kirim WA via WAHA
    try:
        waha_url = "http://waha:3000/api/sendText"
        
        # Susun Payload
        payload = {
            "session": "default",
            "chatId": pending_item.nomor_wa,
            "text": jawaban
        }

        # [UPDATE] Jika ada message_id, tambahkan replyTo agar nge-quote chat user
        if pending_item.message_id:
            payload["replyTo"] = pending_item.message_id

        headers = {"Content-Type": "application/json"}
        if 'WAHA_API_KEY' in globals(): headers["X-Api-Key"] = WAHA_API_KEY
        
        resp = requests.post(waha_url, json=payload, headers=headers)
        
        if resp.status_code in [200, 201]:
            pending_item.status = "selesai"
            
            # Simpan ke history
            history_bot = ChatHistory(
                nomor_wa=pending_item.nomor_wa,
                role="assistant",
                message=jawaban
            )
            db.add(history_bot)

            # Jika dicentang, simpan juga ke tabel FAQ
            if save_to_faq:
                # 1. Masukkan ke tabel FAQ (Otak Utama)
                new_faq = FAQ(
                    pertanyaan=pending_item.pertanyaan, 
                    jawaban=jawaban
                )
                db.add(new_faq)
                db.commit() # Commit dulu biar data masuk DB sebelum vector baca

                # 2. Suruh Vector Service Update Otaknya
                try:
                    requests.post("http://vector-container:8080/refresh", timeout=5)
                    print("Vector Index berhasil diperbarui otomatis.")
                except Exception as e:
                    print(f"Berhasil simpan FAQ, tapi gagal update Vector: {e}")

            db.commit()
        else:
            print(f"Gagal kirim WA: {resp.text}")
            
    except Exception as e:
        print(f"Error connecting to WAHA: {e}")

    return RedirectResponse(url="/pending", status_code=303)

@app.get("/update-model")
def update_model():
    try:
        # Kita "colek" endpoint /refresh milik Vector Service (port 8080)
        # Pastikan nama container sesuai dengan docker-compose (vector-container)
        vector_service_url = "http://vector-container:8080/refresh"
        
        response = requests.post(vector_service_url)
        
        if response.status_code == 200:
            return {"message": "Index Vector berhasil diperbarui!"}
        else:
            return {"message": f"Gagal update index: {response.text}"}
            
    except Exception as e:
        print(f"Error triggering vector refresh: {e}")
        return {"message": "Gagal terhubung ke Vector Service. Pastikan container vector nyala."}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)