import os
import json
import logging
import time
import re
import nltk
import copy
from dotenv import load_dotenv
from groq import Groq
from google import genai  
from google.genai import types

load_dotenv()

# ==============================================================================
# POMOCNICZA FUNKCJA DO KONWERSJI Z .ENV (Tekst -> Boolean)
# ==============================================================================
def get_env_bool(key, default=True):
    val = os.environ.get(key, str(default)).strip().lower()
    return val in ("true", "1", "yes", "on")

# Pobieranie przełączników systemów bezpośrednio z pliku .env
USE_GROQ = get_env_bool("SYSTEM_USE_GROQ", default=True)
USE_GEMINI = get_env_bool("SYSTEM_USE_GEMINI", default=False)
# ==============================================================================

# ==============================================================================
# KONFIGURACJA ŚRODOWISKOWA (Pobierana z pliku .env)
# ==============================================================================
PRODUCT_ID = os.environ.get("CENEO_PRODUCT_ID")
LOGS_DIR = os.environ.get("SYSTEM_LOGS_DIR", "logs")
REVIEWS_DIR = os.environ.get("SYSTEM_REVIEWS_DIR", "reviews")

# Konfiguracja GROQ
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MODELS_STRING = os.environ.get("GROQ_MODELS_LIST", "qwen/qwen3-32b,llama-3.1-8b-instant,openai/gpt-oss-20b")
GROQ_MODELS = [m.strip() for m in MODELS_STRING.split(",")] if USE_GROQ else []

# Konfiguracja GEMINI
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")

# Dynamiczny rozmiar paczki opinii pobierany z pliku .env (domyślnie 10)
BATCH_SIZE = int(os.environ.get("SYSTEM_BATCH_SIZE", 10))
# ==============================================================================

# ==============================================================================
# GŁÓWNY SKRYPT
# ==============================================================================


# Funkcja pomocnicza tekstowa: Dzieli ciągły tekst opinii na pojedyncze zdania przy użyciu tokenizatora NLTK dla języka polskiego.
def split_into_sentences(text):
    return nltk.sent_tokenize(text, language='polish')


# Funkcja pomocnicza heurystyczna: Sprawdza za pomocą wyrażeń regularnych, czy opinia jest pustym, powtarzalnym szablonem i od razu klasyfikuje jej podstawowy sentyment.
def is_empty_template_review(text):
    txt = text.strip().lower()
    positive_patterns = [
        r"^ocena \d/5\s*-\s*bardzo dobrze$",
        r"^ocena \d/5\s*-\s*dobrze$",
        r"^\d\s*-\s*bardzo dobrze$",
        r"^wszystko ok\.?\s*polecam\.?$",
        r"^produkt zgodny z opisem\.?$"
    ]
    for pattern in positive_patterns:
        if re.match(pattern, txt):
            return True, "pozytywny"
    if "ocena 1/5" in txt or ("ocena 2/5" in txt and "źle" in txt):
        return True, "negatywny"
    return False, None


# Funkcja pomocnicza promptu: Generuje strukturyzowaną treść zapytania (prompt) do modeli LLM z instrukcją ABSA i szablonem wymaganego formatu JSON.
def generate_batch_prompt(reviews_to_analyze, product_title):
    reviews_formatted = []
    expected_ids = []
    for rev in reviews_to_analyze:
        r_id = rev['review_number']
        expected_ids.append(str(r_id))
        sentences_formatted = "\n".join([f"  - [{i+1}] {s}" for i, s in enumerate(rev['sentences'])])
        reviews_formatted.append(
            f"--- START RECENZJI ID: {r_id} ---\n"
            f"Pełny tekst:\n\"{rev['review_content']}\"\n\n"
            f"Podział na zdania:\n{sentences_formatted}\n"
            f"--- KONIEC RECENZJI ID: {r_id} ---"
        )
    
    all_reviews_text = "\n\n".join(reviews_formatted)
    ids_str = ", ".join(expected_ids)
    
    return f"""Analizujesz zestaw dokładnie {len(reviews_to_analyze)} recenzji produktu w języku polskim pod kątem ABSA (Aspect-Based Sentiment Analysis) oraz emocji (taksonomia Ekmana: radość, smutek, strach, gniew, zaskoczenie, wstręt, lub brak).

Analizowany produkt to: "{product_title}"

Oto lista recenzji do przeanalizowania:
{all_reviews_text}

Wskazówki: 
1. Przeanalizuj każdą recenzję jako całość, a następnie każde jej zdanie z osobna. Wyciągaj aspekty naturalnie pasujące do tego typu produktu.
2. Musisz zwrócić analizę dla KAŻDEJ z przesłanych recenzji. Oczekiwane numery ID recenzji w Twojej odpowiedzi to dokładnie: {ids_str}. Nie pomijaj żadnego ID!

Odpowiedz WYŁĄCZNIE w formacie JSON zawierającym tablicę obiektów przypisanych do klucza "reviews". Zachowaj dokładnie poniższą strukturę (nie dodawaj żadnych wstępów, komentarzy ani znaczników ```json):

{{
  "reviews": [
    {{
      "review_number": WSTAW_ODPOWIEDNIE_ID_RECENZJI,
      "full_review": {{
        "sentiment": "pozytywny / negatywny / neutralny",
        "emotion": "nazwa_emocji",
        "aspects": ["aspekt1", "aspekt2"]
      }},
      "sentences": [
        {{
          "sentence_number": 1,
          "sentiment": "pozytywny / negatywny / neutralny",
          "emotion": "nazwa_emocji",
          "aspects": ["konkretny aspekt ze zdania"]
        }}
      ]
    }}
  ]
}}
"""


# Główna funkcja wykonawcza potoku (Pipeline): Zarządza pętlą paczkowania, obsługą limitów (Rate Limits) i bezpośrednią komunikacją z API wybranej platformy LLM.
def process_model_pipeline(model_name, platform, client, reviews_to_analyze, template_results, product_title):
    logging.info(f"--- START BATCH ANALIZY DLA MODELU: {model_name} ({platform}) ---")
    
    model_reviews_map = {k: copy.deepcopy(v) for k, v in template_results.items()}
    
    if reviews_to_analyze:
        for chunk_idx in range(0, len(reviews_to_analyze), BATCH_SIZE):
            chunk = reviews_to_analyze[chunk_idx : chunk_idx + BATCH_SIZE]
            
            logging.info(f"Wysyłanie paczki ({len(chunk)} recenzji) do {model_name}...")
            prompt = generate_batch_prompt(chunk, product_title)
            
            success = False
            retries = 0
            max_retries = 5
            
            while not success and retries < max_retries:
                try:
                    raw_response = ""
                    
                    # ----------------------------------------------------------
                    # SEKCJA: WYWOŁANIA MODELI (API CALLS)
                    # ----------------------------------------------------------
                    if platform == "GROQ":
                        chat_completion = client.chat.completions.create(
                            model=model_name,
                            messages=[{"role": "user", "content": prompt}],
                            response_format={"type": "json_object"}
                        )
                        raw_response = chat_completion.choices[0].message.content
                    
                    elif platform == "GEMINI":
                        response = client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json"
                            ),
                        )
                        raw_response = response.text
                    # ----------------------------------------------------------
                    
                    llm_res = json.loads(raw_response)
                    
                    for batch_rev in llm_res.get("reviews", []):
                        r_num = batch_rev.get("review_number")
                        orig_rev = next((r for r in chunk if r["review_number"] == r_num), None)
                        
                        if orig_rev:
                            model_reviews_map[r_num] = {
                                "review_number": r_num,
                                "full_review": {"text": orig_rev["review_content"], **batch_rev.get("full_review", {})},
                                "sentences": [
                                    {
                                        "sentence_number": s.get("sentence_number"),
                                        "text": orig_rev["sentences"][i] if i < len(orig_rev["sentences"]) else "",
                                        "sentiment": s.get("sentiment"),
                                        "emotion": s.get("emotion"),
                                        "aspects": s.get("aspects")
                                    } for i, s in enumerate(batch_rev.get("sentences", []))
                                ]
                            }
                    
                    logging.info(f" -> Paczka od indeksu {chunk_idx} dla {model_name} pobrana pomyślnie.")
                    success = True
                    
                except Exception as api_err:
                    err_msg = str(api_err)
                    if "429" in err_msg or "rate_limit" in err_msg.lower() or "quota" in err_msg.lower():
                        retries += 1
                        wait_time = 20 * retries
                        logging.warning(f"  [Limit Prędkości] Próba {retries}/{max_retries}. Czekam {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logging.error(f"  [BŁĄD PACZKI] Problem przy indeksie {chunk_idx} w modelu {model_name}: {api_err}")
                        break
            
            time.sleep(2.0)
            
    sorted_results = [model_reviews_map[k] for k in sorted(model_reviews_map.keys())]
    
    total_evaluated = len(sorted_results)
    pos_count = neg_count = neu_count = 0
    for res in sorted_results:
        sentiment = str(res.get("full_review", {}).get("sentiment", "")).lower()
        if "pozytywny" in sentiment: pos_count += 1
        elif "negatywny" in sentiment: neg_count += 1
        elif "neutralny" in sentiment: neu_count += 1
        
    logging.info(f"=== PODSUMOWANIE STATYSTYK DLA MODELU: {model_name} ===")
    logging.info(f" -> Wszystkich ocenionych opinii: {total_evaluated}")
    logging.info(f" -> Pozytywne: {pos_count} | Neutralne: {neu_count} | Negatywne: {neg_count}")
    logging.info("======================================================")
    
    return {
        "model_name": f"{platform.lower()}-{model_name.replace('/', '-')}",
        "metrics": {
            "total_reviews_evaluated": total_evaluated,
            "sentiment_breakdown": {"positive": pos_count, "neutral": neu_count, "negative": neg_count}
        },
        "reviews": sorted_results
    }


# Główna funkcja: Inicjalizuje środowisko, ładuje plik wejściowy JSON, przeprowadza filtrację szablonów i sekwencyjnie uruchamia wybrane platformy AI.
def analyze_reviews(product_id):
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = os.path.join(LOGS_DIR, f"{product_id}.log")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.FileHandler(log_file, encoding='utf-8'), logging.StreamHandler()]
    )

    logging.info("=== URUCHOMIENIE SKRYPTU BATCH MULTI-MODEL ===")
    logging.info(f"Konfiguracja platform z .env -> GROQ: {USE_GROQ} | GEMINI: {USE_GEMINI} | Rozmiar paczki: {BATCH_SIZE}")
    
    if not USE_GROQ and not USE_GEMINI:
        logging.error("BŁĄD: Wyłączyłeś obie platformy (GROQ i GEMINI) w pliku .env. Brak modeli do przetworzenia!")
        return

    # --------------------------------------------------------------------------
    # SEKCJA: INICJALIZACJA KLIENTÓW API (INITIALIZATION)
    # --------------------------------------------------------------------------
    groq_client = None
    if USE_GROQ:
        if not GROQ_API_KEY:
            logging.error("BŁĄD: Brak klucza GROQ_API_KEY w pliku .env!")
            return
        groq_client = Groq(api_key=GROQ_API_KEY)
        logging.info(f"Aktywne modele Groq: {GROQ_MODELS}")
        
    gemini_client = None
    if USE_GEMINI:
        if not GEMINI_API_KEY:
            logging.error("BŁĄD: Brak klucza GEMINI_API_KEY w pliku .env!")
            return
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logging.info(f"Aktywny model Gemini: {GEMINI_MODEL_NAME}")
    # --------------------------------------------------------------------------

    try:
        nltk.data.find('tokenizers/punkt_tab')
    except LookupError:
        nltk.download('punkt_tab', quiet=True)

    product_dir = os.path.join(REVIEWS_DIR, product_id)
    input_filename = f"review_{product_id}.json"
    input_path = os.path.join(product_dir, input_filename)

    if not os.path.exists(input_path):
        logging.error(f"Nie znaleziono pliku źródłowego: {input_path}")
        return

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    product_title = data.get("title", "Nieznany produkt")
    reviews = data.get("reviews", [])
    
    # --------------------------------------------------------------------------
    # SEKCJA: PRZYGOTOWANIE I FILTRACJA DANYCH (DATA PREPARATION)
    # --------------------------------------------------------------------------
    template_results = {}
    reviews_to_analyze = []

    for rev in reviews:
        rev_num = rev.get("review_number")
        rev_content = rev.get("review_content")
        
        is_template, auto_sentiment = is_empty_template_review(rev_content)
        if is_template:
            template_results[rev_num] = {
                "review_number": rev_num,
                "full_review": {"text": rev_content, "sentiment": auto_sentiment, "emotion": "brak", "aspects": []},
                "sentences": [{"sentence_number": 1, "text": rev_content, "sentiment": auto_sentiment, "emotion": "brak", "aspects": []}]
            }
        else:
            reviews_to_analyze.append({
                "review_number": rev_num,
                "review_content": rev_content,
                "sentences": split_into_sentences(rev_content)
            })

    all_models_analysis_results = []
    # --------------------------------------------------------------------------

    # --------------------------------------------------------------------------
    # SEKCJA: WYKONYWANIE PROCESÓW ANALITYCZNYCH LLM (EXECUTION)
    # --------------------------------------------------------------------------
    if USE_GROQ:
        for model_name in GROQ_MODELS:
            res = process_model_pipeline(model_name, "GROQ", groq_client, reviews_to_analyze, template_results, product_title)
            all_models_analysis_results.append(res)
            time.sleep(4.0)

    if USE_GEMINI:
        res = process_model_pipeline(GEMINI_MODEL_NAME, "GEMINI", gemini_client, reviews_to_analyze, template_results, product_title)
        all_models_analysis_results.append(res)
        time.sleep(4.0)
    # --------------------------------------------------------------------------

    final_json = {
        "input_file": input_filename,
        "product_id": product_id,
        "product_title": product_title,
        "analysis_results": all_models_analysis_results
    }

    output_filename = f"analysis_review_decoder_{product_id}.json"
    output_path = os.path.join(product_dir, output_filename)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)

    logging.info(
        f"=== ZAKOŃCZONO PROCES BATCH. Zbiorcze wyniki zapisane w: {output_path} ==="
    )

if __name__ == "__main__":
    if not PRODUCT_ID:
        print("BŁĄD: Brak zdefiniowanego CENEO_PRODUCT_ID w pliku .env!")
    else:
        analyze_reviews(PRODUCT_ID)