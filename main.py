from fastapi import FastAPI, HTTPException, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Optional
import uvicorn
from model.hybrid_instance import *
from model.hybrid_search import *
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

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
async def read_faqs(request: Request, q: Optional[str] = None, db: Session = Depends(get_db)):
    if q:
        faqs = db.query(FAQ).filter(FAQ.pertanyaan.like(f"%{q}%")).all()
    else:
        faqs = db.query(FAQ).all()
    return templates.TemplateResponse("index.html", {
            "request": request, "faqs": faqs, "query": q
        }
    )

@app.post("/add")
async def add_faq(pertanyaan: str = Form(...), jawaban: str = Form(...), db: Session = Depends(get_db)):
    faq = FAQ(pertanyaan=pertanyaan, jawaban=jawaban)
    db.add(faq)
    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/edit/{faq_id}", response_class=HTMLResponse)
async def edit_faq_form(request: Request, faq_id: int, q: Optional[str] = None, db: Session = Depends(get_db)):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ tidak ditemukan")
    return templates.TemplateResponse("edit.html", {"request": request, "faq": faq, "query": q})

@app.post("/edit/{faq_id}")
async def edit_faq(
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
async def delete_faq(request: Request, faq_id: int, db: Session = Depends(get_db)):
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ tidak ditemukan")
    db.delete(faq)
    db.commit()

    referer = request.headers.get("referer")
    return RedirectResponse(url=referer if referer else "/", status_code=303)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
