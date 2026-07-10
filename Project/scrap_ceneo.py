# ==============================================================================
# BIBLIOTEKI
# ==============================================================================
import os
import time
import logging
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
# ==============================================================================
# ==============================================================================

# Wczytanie zmiennych środowiskowych z pliku .env
load_dotenv()

# ==============================================================================
# KONFIGURACJA SKRYPTU (Pobrana WYŁĄCZNIE z pliku .env)
# ==============================================================================

# Ustawienia ogólne ceneo
PRODUCT_ID = os.environ.get("CENEO_PRODUCT_ID")
BASE_URL = os.environ.get("CENEO_BASE_URL")

# Ustawienia ogólne systemu
LOGS_DIR = os.environ.get("SYSTEM_LOGS_DIR")
REVIEWS_DIR = os.environ.get("SYSTEM_REVIEWS_DIR")
USER_AGENT = os.environ.get("SYSTEM_USER_AGENT")
# ==============================================================================
# ==============================================================================


# ==============================================================================
# GŁÓNY SKRYPT
# ==============================================================================


# Funkcja scrape_ceneo() pobiera opinie o produkcie i zapisuje je do plików HTML.
def scrape_ceneo(product_id):
    
    # Tworzenie katalogu na logi jeśli nie istnieje (pobrane z .env)
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = os.path.join(LOGS_DIR, f"{product_id}.log")

    # Konfiguracja logowania do pliku i na konsolę
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    logging.info(f"Rozpoczynam proces pobierania opinii dla produktu ID: {product_id}")

    # Definiowanie ścieżki docelowej dla plików HTML i tworzenie struktury katalogów
    output_dir = os.path.join(REVIEWS_DIR, product_id)
    os.makedirs(output_dir, exist_ok=True)

    with sync_playwright() as p:
        # Inicjalizacja przeglądarki Chromium w trybie bezinterfejsowym
        browser = p.chromium.launch(headless=True)
        # Konfiguracja kontekstu przeglądarki z parametrami z .env
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="pl-PL",
            user_agent=USER_AGENT
        )
        page = context.new_page()

        page_num = 1

        # Pętla iterująca po kolejnych stronach opinii
        while True:
            target_url = f"{BASE_URL}/{product_id}/opinie-{page_num}"
            output_filename = os.path.join(output_dir, f"ceneo_{product_id}_strona_{page_num}.html")

            logging.info(f"--- [STRONA {page_num}] ---")
            logging.info(f"Próba pobrania: {target_url}")

            try:
                # Nawigacja do strony z opiniami
                page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

                # Oczekiwanie na pełne załadowanie dynamicznej zawartości i skryptów strony
                time.sleep(3)

                actual_url = page.url

                # Weryfikacja adresu URL w celu uniknięcia zapętlenia przy braku kolejnych stron
                if page_num == 1:
                    # Sprawdzenie czy pierwsza strona jest poprawna
                    if f"opinie-1" not in actual_url and actual_url.rstrip(
                            '/') != f"{BASE_URL}/{product_id}" and "tab=reviews" not in actual_url:
                        logging.warning(f" Strona 1 przekierowała na nieoczekiwany adres: {actual_url}")
                        break
                    else:
                        logging.info(f" Adres strony 1 zweryfikowany poprawnie (URL: {actual_url})")
                else:
                    # Jeśli URL nie zawiera numeru strony, oznacza to prawdopodobnie przekierowanie na stronę główną produktu (koniec opinii)
                    if f"opinie-{page_num}" not in actual_url:
                        logging.info(f" Wykryto koniec stron (automatyczne przekierowanie na: {actual_url})")
                        break

                # Symulacja przewijania strony za pomocą klawiatury w celu aktywacji skryptów ładowania zawartości
                logging.info(" Przewijam stronę w dół (PageDown)...")
                for _ in range(6):
                    try:
                        page.keyboard.press("PageDown")
                        time.sleep(0.5)
                    except Exception:
                        # W przypadku chwilowej utraty dostępności elementu sterującego, ponawiamy próbę po krótkiej przerwie
                        time.sleep(1)
                        continue

                time.sleep(1.5)
                raw_html = page.content()

                # Weryfikacja obecności elementów zawierających treść opinii w kodzie HTML
                if "user-post__text" not in raw_html:
                    print(f" Nie znaleziono opinii w strukturze strony {page_num}. Zakończono pobieranie.")
                    break

                # Zapis pobranej zawartości HTML do pliku lokalnego
                with open(output_filename, "w", encoding="utf-8") as f:
                    f.write(raw_html)

                print(f"[ZAPISANO] -> {output_filename}")
                page_num += 1

            except Exception as e:
                # Obsługa błędów wykonawczych wewnątrz pętli w celu zachowania ciągłości pracy skryptu
                print(f" Wystąpił błąd podczas przetwarzania strony {page_num}: {e}")
                print(" Próba awaryjnego odczytu zawartości...")
                try:
                    raw_html = page.content()
                    if "user-post__text" in raw_html:
                        with open(output_filename, "w", encoding="utf-8") as f:
                            f.write(raw_html)
                        print(f" [AWARYJNY ZAPIS] Zawartość zapisana mimo wystąpienia błędu -> {output_filename}")
                        page_num += 1
                    else:
                        print(" Awaryjne pobieranie nie powiodło się (brak treści). Przerywam pętlę.")
                        break
                except Exception:
                    # W przypadku krytycznego błędu, który uniemożliwia nawet awaryjny odczyt, przerywamy działanie
                    break

            # Odstęp czasowy między żądaniami w celu zachowania optymalnej charakterystyki ruchu sieciowego
            time.sleep(2)

        browser.close()
        print(f"\n[KONIEC] Proces zakończony pomyślnie. Łącznie pobrano stron: {page_num - 1}.")


if __name__ == "__main__":
    # Przed uruchomieniem upewniamy się, że PRODUCT_ID został ustawiony w pliku .env
    if not PRODUCT_ID:
        print("BŁĄD: Brak PRODUCT_ID w pliku .env! Uzupełnij konfigurację.")
    else:
        scrape_ceneo(PRODUCT_ID)

# ==============================================================================
# ==============================================================================        