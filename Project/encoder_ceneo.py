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

MODELS_CACHE_DIR = os.environ.get("HF_HOME", "models")
os.makedirs(MODELS_CACHE_DIR, exist_ok=True)

import torch
import spacy
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification

# ==============================================================================
# UNIWERSALNA EKSTRAKCJA ASPEKTÓW (GENERIC ABSA DLA JĘZYKA POLSKIEGO)
# ==============================================================================

def extract_aspects_generic(nlp_engine, text):
    """
    Uniwersalna ekstrakcja aspektów dla języka polskiego (bez doc.noun_chunks).
    Identyfikuje kluczowe obiekty opinii (rzeczowniki oraz złożone frazy rzeczownikowe i przymiotnikowe)
    za pomocą analizy składniowej (dependency parsing), niezależnie od kategroii sprzętu.
    """
    doc = nlp_engine(text)
    aspects = []

    # Czarna lista ogólnych słów niebędących cechami/aspektami sprzętu
    STOP_ASPECTS = {
        "ocena", "zakup", "produkt", "sprzęt", "dostawa", "sklep", "gwiazdka",
        "złotych", "złoty", "zł", "raz", "dzień", "tydzień", "miesiąc", "rok", "złotówka"
    }

    # 1. Ekstrakcja pojedynczych rzeczowników (NOUN / PROPN)
    for token in doc:
        if token.pos_ in ("NOUN", "PROPN") and not token.is_stop and len(token.text) > 2:
            lemma = token.lemma_.lower()
            if lemma not in STOP_ASPECTS and lemma not in aspects:
                aspects.append(lemma)

            # 2. Ekstrakcja złożonych fraz (np. "jakość wykonania", "czas pracy", "dobry silnik")
            # Przeglądamy poddrzewo relacji gramatycznych tokena (modyfikatory nmod, amod, flat)
            for child in token.children:
                # Frazy: Rzeczownik + Rzeczownik w dopełniaczu (np. jakość -> wykonania, czas -> pracy)
                if child.dep_ in ("nmod", "flat") and child.pos_ in ("NOUN", "PROPN"):
                    compound_phrase = f"{lemma} {child.lemma_.lower()}"
                    if compound_phrase not in aspects:
                        aspects.append(compound_phrase)
                
                # Frazy: Przymiotnik + Rzeczownik (np. cichy -> silnik, świetny -> dźwięk)
                elif child.dep_ == "amod" and child.pos_ == "ADJ" and not child.is_stop:
                    adj_noun_phrase = f"{child.lemma_.lower()} {lemma}"
                    if adj_noun_phrase not in aspects:
                        aspects.append(adj_noun_phrase)

    return aspects

# ==============================================================================
# POMOCNICZE FUNKCJE MAPUJĄCE I PRZETWARZAJĄCE
# ==============================================================================

def split_into_sentences(text):
    return nltk.sent_tokenize(text, language='polish')

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

def map_sentiment_label(label):
    lbl = str(label).lower()
    if "5 star" in lbl or "4 star" in lbl: return "pozytywny"
    if "3 star" in lbl: return "neutralny"
    if "2 star" in lbl or "1 star" in lbl: return "negatywny"
    
    if "pos" in lbl or "positive" in lbl: return "pozytywny"
    if "neg" in lbl or "negative" in lbl: return "negatywny"
    if "neu" in lbl or "neutral" in lbl: return "neutralny"
    
    return "neutralny"

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

def load_local_or_remote_pipeline(task, model_name, cache_dir, device):
    hf_folder_format = f"models--{model_name.replace('/', '--')}"
    expected_local_path = os.path.join(cache_dir, hf_folder_format)
    
    if os.path.exists(expected_local_path):
        logging.info(f" -> [LOKALNY CACHE] Ładowanie z dysku: {model_name}")
        tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir, local_files_only=True)
        model = AutoModelForSequenceClassification.from_pretrained(model_name, cache_dir=cache_dir, local_files_only=True)
        return pipeline(task, model=model, tokenizer=tokenizer, device=device)
    else:
        logging.warning(f" -> [POBIERANIE HF] Pobieranie: {model_name}...")
        tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
        model = AutoModelForSequenceClassification.from_pretrained(model_name, cache_dir=cache_dir)
        return pipeline(task, model=model, tokenizer=tokenizer, device=device)

# ==============================================================================
# GŁÓWNA PĘTLA PRZETWARZANIA
# ==============================================================================

def analyze_reviews_encoder(product_id):
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = os.path.join(LOGS_DIR, f"{product_id}.log")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.FileHandler(log_file, encoding='utf-8'), logging.StreamHandler()]
    )

    logging.info("=== URUCHOMIENIE UNIWERSALNEGO SKRYPTU MACIERZY ENKODERÓW ===")
    
    device = 0 if torch.cuda.is_available() else -1
    logging.info(f"Używane urządzenie obliczeniowe: {'GPU (CUDA)' if device == 0 else 'CPU'}")

    model_pairs = list(itertools.product(MODEL_SENTIMENT_VERSIONS, MODEL_EMOTION_VERSIONS))
    
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
            logging.error(f"Pominięcie pary z powodu błędu: {pair_init_err}")
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
                
                processed_sentences = []
                aggregated_aspects = []
                
                for s_idx, s_text in enumerate(r_sentences):
                    if not s_text.strip():
                        continue
                    
                    s_sent_res = sentiment_pipeline(s_text[:512])[0]
                    s_emo_res = emotion_pipeline(s_text[:512])[0]
                    
                    s_sentiment = map_sentiment_label(s_sent_res['label'])
                    s_emotion = map_emotion_label(s_emo_res['label'])
                    
                    # Uniwersalna ekstrakcja aspektów
                    s_aspects = extract_aspects_generic(nlp_engine, s_text)
                    
                    # Agregacja do poziomu pełnej opinii
                    for asp in s_aspects:
                        if asp not in aggregated_aspects:
                            aggregated_aspects.append(asp)
                    
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
                        "aspects": aggregated_aspects
                    },
                    "sentences": processed_sentences
                }
                
            except Exception as proc_err:
                logging.error(f"Błąd przetwarzania opinii ID {r_num}: {proc_err}")

        sorted_results = [model_reviews_map[k] for k in sorted(model_reviews_map.keys())]
        
        pos_count = sum(1 for res in sorted_results if "pozytywny" in str(res.get("full_review", {}).get("sentiment", "")).lower())
        neg_count = sum(1 for res in sorted_results if "negatywny" in str(res.get("full_review", {}).get("sentiment", "")).lower())
        neu_count = sum(1 for res in sorted_results if "neutralny" in str(res.get("full_review", {}).get("sentiment", "")).lower())
            
        execution_time = round(time.time() - pair_start_time, 2)

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

if __name__ == "__main__":
    if PRODUCT_ID:
        analyze_reviews_encoder(PRODUCT_ID)
