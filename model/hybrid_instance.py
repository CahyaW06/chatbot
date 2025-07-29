import mysql.connector
from sentence_transformers import SentenceTransformer
from functools import lru_cache
from config import *

def load_faq():
    conn = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM pertanyaan")
    faq = cursor.fetchall()

    cursor.close()
    conn.close()

    return faq

@lru_cache(maxsize=1)
def get_model(model_name='intfloat/multilingual-e5-small'):
    return SentenceTransformer(model_name)

def load_cache(session_id):
    return chat_memory.get(session_id, [])

def load_context(session_id):
    history = load_cache(session_id)
    return " ".join([entry["query"] if entry["query"] else "" for entry in history])

def save_cache(session_id, query, results):
    if session_id not in chat_memory:
        chat_memory[session_id] = []
    chat_memory[session_id].append({
        "query": query,
        "results": results
    })

def clear_cache():
    global chat_memory

    chat_memory = {}
    print('chat_memory has been cleared.')
