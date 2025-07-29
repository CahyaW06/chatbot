import numpy as np
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as cos_sim
from .hybrid_instance import *
# import redis

class HybridSearch:
    def __init__(self, model_name='intfloat/multilingual-e5-small', top_k=1, redis_host='localhost', redis_port=6379):
        self.model = get_model(model_name)
        self.top_k = top_k
        self.ttl = 28800

        # # Redis
        # self.redis = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)

    def build_index(self, faq):
        self.faq_questions = [item[1] for item in faq]
        self.faq_answers = [item[2] for item in faq]

        self.tfidf_vectorizer = TfidfVectorizer()
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(self.faq_questions)

        self.semantic_embeddings = self.model.encode(self.faq_questions, normalize_embeddings=True)

    def search(self, query, session_id=None, use_cache=False):
        # dict
        cached = None
        if session_id:
            cached = load_context(session_id) if use_cache is True else ""

        # Step 1: TF-IDF filter
        tfidf_queries = self.preprocess_text(query)  # hanya query baru

        best_tfidf_score = 0
        best_query = None
        best_tfidf_query = None

        # Precompute TF-IDF dari cached (memori lama)
        cached_score = None
        if cached:
            cached_tfidf = self.tfidf_vectorizer.transform([cached])
            cached_score = cos_sim(cached_tfidf, self.tfidf_matrix)[0]
            cached_score *= 0.3  # Bobot 30% dari konteks lama

        for paragraph in tfidf_queries:
            tfidf_query = self.tfidf_vectorizer.transform([paragraph])
            tfidf_scores = cos_sim(tfidf_query, self.tfidf_matrix)[0]

            # Bobot tambahan jika ada tanda tanya
            tfidf_scores *= 1.2 if self.is_question(paragraph) else tfidf_scores

            # Gabungkan skor baru dengan skor lama jika ada
            if cached_score is not None:
                combined_score = tfidf_scores * 0.7 + cached_score
            else:
                combined_score = tfidf_scores

            highest_score = max(combined_score)
            if highest_score > best_tfidf_score:
                best_query = paragraph
                best_tfidf_score = highest_score
                best_tfidf_query = combined_score
                print(f"question: {paragraph}")
                print(f"related question: {self.faq_questions[np.argmax(combined_score)]}")
                print(f"score: {highest_score}")

        if best_tfidf_query is None or best_tfidf_score < 0.5:
            results = [(best_query, "", 0.0)]
        else:
            top_k_indices = np.argsort(best_tfidf_query)[::-1][:self.top_k]
            top_k_faqs = [self.faq_questions[i] for i in top_k_indices]
            top_k_answer = [self.faq_answers[i] for i in top_k_indices]

            # Step 2: Semantic reranking
            query_embedding = self.model.encode([query], normalize_embeddings=True)
            selected_embeddings = self.semantic_embeddings[top_k_indices]
            semantic_scores = np.dot(query_embedding, selected_embeddings.T)[0]

            # Sort top-k by semantic similarity
            final_rank = np.argsort(semantic_scores)[::-1]
            results = [(top_k_faqs[i], top_k_answer[i], float(semantic_scores[i])) for i in final_rank]

        # dict
        if session_id and use_cache is True:
            save_cache(session_id, best_query, results)

        return results

    def preprocess_text(self, text, cached=None):
        text = self.cleaning_tanda_baca_berulang(text)
        texts = self.spliting_paragraph(text, cached)
        processed_texts = []

        for text in texts:
            text = text.lower()
            text = self.append_titik(text)
            processed_texts.append(text)

        return processed_texts

    def cleaning_tanda_baca_berulang(self, text):
        return re.sub(r'([!?.;,:\-\n])\1+', r'\1', text)

    def append_titik(self, text):
        if not text.endswith(('.', '?', '!')):
            return text + '.'
        return text

    def spliting_paragraph(self, text, cached=None):
        paragraph = text.split('\n')
        return paragraph

    def is_question(self, text):
        if '?' in text:
            return True
        return False
