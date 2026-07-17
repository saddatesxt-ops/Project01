import os
import json
import logging
import time
import re
import nltk
import copy
import itertools
from dotenv import load_dotenv

# Ładowanie zmiennych z .env PRZED importem torch i transformers
load_dotenv()

# ==============================================================================
# KONFIGURACJA ŚRODOWISKOWA (Pobierana z pliku .env)
# ==============================================================================
PRODUCT_ID = os.environ.get("CENEO_PRODUCT_ID")
LOGS_DIR = os.environ.get("SYSTEM_LOGS_DIR", "logs")
REVIEWS_DIR = os.environ.get("SYSTEM_REVIEWS_DIR", "reviews")
SPACY_MODEL_NAME = os.environ.get("ENCODER_SPACY_MODEL", "pl_core_news_md")

SENTIMENT_LIST_RAW = os.environ.get("ENCODER_MODEL_SENTIMENT_LIST", "nlptown/bert-base-multilingual-uncased-sentiment")
EMOTION_LIST_RAW = os.environ.get("ENCODER_MODEL_EMOTION_LIST", "FacebookAI/xlm-roberta-base")

MODEL_SENTIMENT_VERSIONS = [m.strip() for m in SENTIMENT_LIST_RAW.split(",") if m.strip()]
MODEL_EMOTION_VERSIONS = [m.strip() for m in EMOTION_LIST_RAW.split(",") if m.strip()]

# Skrypt korzysta teraz bezpośrednio ze zunifikowanej zmiennej HF_HOME
MODELS_CACHE_DIR = os.environ.get("HF_HOME", "models")
os.makedirs(MODELS_CACHE_DIR, exist_ok=True)
# ==============================================================================

import torch
import spacy
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
from transformers.utils import is_offline_mode

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

# Funkcja mapowania: Standaryzuje etykiety gwiazdkowe, numeryczne lub tekstowe z modeli klasyfikacji sentymentu do wspólnego formatu.
def map_sentiment_label(label):
    lbl = str(label).lower()
    if "5 star" in lbl or "4 star" in lbl: return "pozytywny"
    if "3 star" in lbl: return "neutralny"
    if "2 star" in lbl or "1 star" in lbl: return "negatywny"
    
    if "pos" in lbl or "positive" in lbl or "prawdopodobieństwo sukcesu" in lbl: return "pozytywny"
    if "neg" in lbl or "negative" in lbl: return "negatywny"
    if "neu" in lbl or "neutral" in lbl: return "neutralny"
    
    return "neutralny"

# Funkcja mapowania: Konwertuje wielojęzyczne oraz wieloklasowe etykiety modeli detekcji emocji na uogólnione kategorie taksonomii Ekmana.
def map_emotion_label(label):
    lbl = str(label).strip().lower()
    
    polish_emotions_map = {
        "radość": "radość", "podziw": "radość", "rozrywka": "radość", "aprobata": "radość", 
        "troska": "radość", "pragnienie": "radość", "ekscytacja": "radość", "wdzięczność": "radość", 
        "miłość": "radość", "optymizm": "radość", "duma": "radość", "ulga": "radość",
        
        "gniew": "gniew", "złość": "gniew", "irytacja": "gniew", "dezaprobata": "gniew",
        
        "smutek": "smutek", "rozczarowanie": "smutek", "zażenowanie": "smutek", "żal": "smutek",
        
        "strach": "strach", "nerwowość": "strach",
        
        "wstręt": "wstręt", "obrzydzenie": "wstręt",
        
        "zaskoczenie": "zaskoczenie", "uświadomienie": "zaskoczenie",
        
        "ciekawość": "neutralny", "neutralny": "brak", "neutral": "brak"
    }
    if lbl in polish_emotions_map:
        return polish_emotions_map[lbl]

    lbl_upper = lbl.upper()
    classic_mapping = {
        "LABEL_0": "brak", "LABEL_1": "radość", "LABEL_2": "smutek", 
        "LABEL_3": "strach", "LABEL_4": "gniew", "LABEL_5": "zaskoczenie", "LABEL_6": "wstręt",
        "JOY": "radość", "SADNESS": "smutek", "FEAR": "strach", 
        "ANGER": "gniew", "SURPRISE": "zaskoczenie", "DISGUST": "wstręt", "NEUTRAL": "brak"
    }
    if lbl_upper in classic_mapping:
        return classic_mapping[lbl_upper]

    if len(lbl) > 0 and not lbl.startswith("label_"):
        return label

    return "brak"

# Funkcja ekstrakcji: Wyciąga unikalne aspekty rzeczownikowe z tekstu za pomocą analizy składniowej i lematyzacji silnika spaCy.
def extract_aspects_from_sentence(nlp_engine, text):
    doc = nlp_engine(text)
    aspects = []
    for token in doc:
        if token.pos_ in ("NOUN", "PROPN"):
            if not token.is_stop and len(token.text) > 2:
                lemma = token.lemma_.lower()
                if lemma not in aspects:
                    aspects.append(lemma)
    return aspects

# Zoptymalizowana funkcja ładowania modeli oparta o natywny mechanizm HF offline
def load_local_or_remote_pipeline(task, model_name, cache_dir, device):
    if os.environ.get("HF_HUB_OFFLINE") == "1" or is_offline_mode():
        logging.info(f" -> [OFFLINE] Ładowanie modelu z lokalnego cache: {model_name}")
        tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir, local_files_only=True)
        model = AutoModelForSequenceClassification.from_pretrained(model_name, cache_dir=cache_dir, local_files_only=True)
        return pipeline(task, model=model, tokenizer=tokenizer, device=device)
    else:
        logging.warning(f" -> [ONLINE] Tryb sieciowy aktywowany. Pobieranie/Sprawdzanie {model_name}...")
        tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
        model = AutoModelForSequenceClassification.from_pretrained(model_name, cache_dir=cache_dir)
        return pipeline(task, model=model, tokenizer=tokenizer, device=device)

# Główna funkcja orkiestratora
def analyze_reviews_encoder(product_id):
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = os.path.join(LOGS_DIR, f"{product_id}.log")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.FileHandler(log_file, encoding='utf-8'), logging.StreamHandler()]
    )

    logging.info("=== URUCHOMIENIE SKRYPTU MACIERZY ENKODERÓW LOKALNYCH ===")
    
    device = 0 if torch.cuda.is_available() else -1
    logging.info(f"Używane urządzenie obliczeniowe: {'GPU (CUDA)' if device == 0 else 'CPU'}")
    logging.info(f"Status trybu HuggingFace Offline: {os.environ.get('HF_HUB_OFFLINE') == '1'}")

    model_pairs = list(itertools.product(MODEL_SENTIMENT_VERSIONS, MODEL_EMOTION_VERSIONS))
    logging.info(f"Wykryte modele sentymentu: {len(MODEL_SENTIMENT_VERSIONS)}")
    logging.info(f"Wykryte modele emocji: {len(MODEL_EMOTION_VERSIONS)}")
    logging.info(f"Łączna liczba par do przetestowania (Matrix): {len(model_pairs)}")

    try:
        logging.info(f"Ładowanie silnika językowego spaCy: {SPACY_MODEL_NAME}...")
        nlp_engine = spacy.load(SPACY_MODEL_NAME)
    except Exception as spacy_err:
        logging.error(f"BŁĄD spaCy: {spacy_err}")
        return

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

    logging.info(f"Do przetworzenia przez NLP: {len(reviews_to_analyze)} opinii (odsiano {len(template_results)} szablonów).")
    
    all_analysis_results = []

    for p_idx, (current_sentiment_model, current_emotion_model) in enumerate(model_pairs):
        pair_name = f"sentiment:{current_sentiment_model} + emotion:{current_emotion_model}"
        logging.info(f"\n--- [PARA {p_idx + 1}/{len(model_pairs)}] Uruchamianie konfiguracji: {pair_name}")
        
        try:
            sentiment_pipeline = load_local_or_remote_pipeline(
                task="sentiment-analysis", model_name=current_sentiment_model, 
                cache_dir=MODELS_CACHE_DIR, device=device
            )
            emotion_pipeline = load_local_or_remote_pipeline(
                task="sentiment-analysis", model_name=current_emotion_model, 
                cache_dir=MODELS_CACHE_DIR, device=device
            )
        except Exception as pair_init_err:
            logging.error(f"Pominięcie pary z powodu błędu ładowania: {pair_init_err}")
            continue

        model_reviews_map = {k: copy.deepcopy(v) for k, v in template_results.items()}
        pair_start_time = time.time()

        for idx, rev in enumerate(reviews_to_analyze):
            r_num = rev["review_number"]
            r_content = rev["review_content"]
            r_sentences = rev["sentences"]
            
            try:
                raw_sent_res = sentiment_pipeline(r_content[:512])[0]
                raw_emo_res = emotion_pipeline(r_content[:512])[0]
                
                full_sentiment = map_sentiment_label(raw_sent_res['label'])
                full_emotion = map_emotion_label(raw_emo_res['label'])
                full_aspects = extract_aspects_from_sentence(nlp_engine, r_content)
                
                processed_sentences = []
                for s_idx, s_text in enumerate(r_sentences):
                    if not s_text.strip():
                        continue
                    
                    s_sent_res = sentiment_pipeline(s_text[:512])[0]
                    s_emo_res = emotion_pipeline(s_text[:512])[0]
                    
                    s_sentiment = map_sentiment_label(s_sent_res['label'])
                    s_emotion = map_emotion_label(s_emo_res['label'])
                    s_aspects = extract_aspects_from_sentence(nlp_engine, s_text)
                    
                    processed_sentences.append({
                        "sentence_number": s_idx + 1,
                        "text": s_text,
                        "sentiment": s_sentiment,
                        "emotion": s_emotion,
                        "aspects": s_aspects
                    })
                    
                model_reviews_map[r_num] = {
                    "review_number": r_num,
                    "full_review": {
                        "text": r_content,
                        "sentiment": full_sentiment,
                        "emotion": full_emotion,
                        "aspects": full_aspects
                    },
                    "sentences": processed_sentences
                }
                
            except Exception as proc_err:
                logging.error(f"Błąd przetwarzania opinii ID {r_num} dla obecnej pary: {proc_err}")
                model_reviews_map[r_num] = {
                    "review_number": r_num,
                    "full_review": {"text": r_content, "sentiment": "neutralny", "emotion": "brak", "aspects": []},
                    "sentences": []
                }

        sorted_results = [model_reviews_map[k] for k in sorted(model_reviews_map.keys())]
        
        pos_count = neg_count = neu_count = 0
        for res in sorted_results:
            sentiment = str(res.get("full_review", {}).get("sentiment", "")).lower()
            if "pozytywny" in sentiment: pos_count += 1
            elif "negatywny" in sentiment: neg_count += 1
            elif "neutralny" in sentiment: neu_count += 1
            
        execution_time = round(time.time() - pair_start_time, 2)
        logging.info(f" -> Zakończono. Czas: {execution_time}s | P: {pos_count}, N: {neu_count}, Neg: {neg_count}")

        all_analysis_results.append({
            "model_name": pair_name,
            "metrics": {
                "total_reviews_evaluated": len(sorted_results),
                "execution_time_seconds": execution_time,
                "sentiment_breakdown": {"positive": pos_count, "neutral": neu_count, "negative": neg_count}
            },
            "reviews": sorted_results
        })

        del sentiment_pipeline
        del emotion_pipeline
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    final_json = {
        "input_file": input_filename,
        "product_id": product_id,
        "product_title": product_title,
        "matrix_size": f"{len(MODEL_SENTIMENT_VERSIONS)}x{len(MODEL_EMOTION_VERSIONS)}",
        "analysis_results": all_analysis_results
    }

    output_filename = f"analysis_review_encoder_{product_id}.json"
    output_path = os.path.join(product_dir, output_filename)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)
        
    logging.info(f"\n=== PROCES MACIERZOWY ZAKOŃCZONY. Zbiorcze wyniki zapisano w: {output_path} ===")

if __name__ == "__main__":
    if not PRODUCT_ID:
        print("BŁĄD: Brak zdefiniowanego CENEO_PRODUCT_ID w pliku .env!")
    elif not MODEL_SENTIMENT_VERSIONS or not MODEL_EMOTION_VERSIONS:
        print("BŁĄD: Listy modeli w pliku .env są puste!")
    else:
        analyze_reviews_encoder(PRODUCT_ID)
