import os
import json
import re
import logging
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Wczytanie zmiennych środowiskowych
load_dotenv()

# ==============================================================================
# KONFIGURACJA
# ==============================================================================
PRODUCT_ID = os.environ.get("CENEO_PRODUCT_ID")
REVIEWS_DIR = os.environ.get("SYSTEM_REVIEWS_DIR")
LOGS_DIR = os.environ.get("SYSTEM_LOGS_DIR")


# Funkcja pomocnicza/konfiguracyjna: Inicjalizuje system logowania i tworzy plik logu dla danego produktu.
def setup_logging(product_id, logs_dir):
    if not logs_dir: return
    os.makedirs(logs_dir, exist_ok=True)
    
    log_file = os.path.join(logs_dir, f"{product_id}.log")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (PARSER) %(message)s',
        handlers=[logging.FileHandler(log_file, mode='a', encoding='utf-8'), logging.StreamHandler()]
    )


# Funkcja pomocnicza tekstowa: Wyciąga czysty tekst z elementu HTML i usuwa nadmiarowe białe znaki.
def clean_review_text(div_element):
    text = div_element.get_text(separator=" ")
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# Funkcja pomocnicza: Próbuje wyciągnąć i wyczyścić tytuł produktu z różnych tagów w strukturze HTML.
def get_product_title(soup):
    title_tag = soup.find("h1", class_="product-name")
    
    if not title_tag:
        title_tag = soup.find("h1")
        
    if not title_tag:
        title_tag = soup.find("title")

    if title_tag:
        raw_title = title_tag.get_text(strip=True)
        clean_title = re.sub(r" - Ceny i opinie - Ceneo\.pl$", "", raw_title, flags=re.IGNORECASE)
        return clean_title
    
    return "Nieznany produkt"


# Główna funkcja parsera: Przetwarza pobrane pliki HTML ze stronami Ceneo i zapisuje wyekstrahowane opinie do pliku JSON.
def parse_ceneo_reviews(product_id):
    if not all([product_id, REVIEWS_DIR, LOGS_DIR]):
        print("BŁĄD: Brak zmiennych w .env!")
        return

    setup_logging(product_id, LOGS_DIR)
    target_dir = os.path.join(REVIEWS_DIR, product_id)

    if not os.path.exists(target_dir):
        logging.error(f"Katalog nie istnieje: {target_dir}")
        return

    all_files = [f for f in os.listdir(target_dir) if f.startswith(f"ceneo_{product_id}_strona_")]
    all_files.sort(key=lambda x: int(re.search(r'(\d+)', x).group(1)))

    product_title = None
    reviews_list = []
    review_counter = 1

    for file_name in all_files:
        file_path = os.path.join(target_dir, file_name)
        logging.info(f"Parsowanie: {file_name}")
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f, "html.parser")

                if not product_title:
                    product_title = get_product_title(soup)
                    logging.info(f"Znaleziono produkt: {product_title}")

                review_containers = soup.find_all("div", class_="js_product-review")
                
                for container in review_containers:
                    content_div = container.find("div", class_="user-post__text")
                    if content_div:
                        reviews_list.append({
                            "review_number": review_counter,
                            "review_content": clean_review_text(content_div)
                        })
                        review_counter += 1
                        
        except Exception as e:
            logging.error(f"Błąd w {file_name}: {e}")

    output_path = os.path.join(target_dir, f"review_{product_id}.json")
    with open(output_path, "w", encoding="utf-8") as json_file:
        json.dump({"product_id": product_id, "title": product_title, "reviews": reviews_list}, 
                  json_file, ensure_ascii=False, indent=4)

    logging.info(f"Zakończono. Zebrano {review_counter - 1} opinii. Plik: {output_path}")

if __name__ == "__main__":
    parse_ceneo_reviews(PRODUCT_ID)