from dotenv import load_dotenv
import os

load_dotenv()

# load env
DB_HOST=os.getenv("DB_HOST")
DB_NAME=os.getenv("DB_NAME")
DB_USER=os.getenv("DB_USER")
DB_PASSWORD=os.getenv("DB_PASSWORD")
DB_PORT=os.getenv("DB_PORT")
PORT = os.getenv("PORT", 8000) # Default to 8000 if not set

WAHA_API_KEY=os.getenv("WAHA_API_KEY")
HF_HOME = os.getenv("HF_HOME")
