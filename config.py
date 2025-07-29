from dotenv import load_dotenv
import os

load_dotenv()

# load env
DB_HOST=os.getenv("DB_HOST")
DB_NAME=os.getenv("DB_NAME")
DB_USER=os.getenv("DB_USER")
DB_PASSWORD=os.getenv("DB_PASSWORD")

def initiate_chatbot():
    from model.hybrid_instance import load_faq
    from model.hybrid_search import HybridSearch

    model_faq = load_faq(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME)
    chatbot = HybridSearch()
    chatbot.build_index(model_faq)

    return chatbot
