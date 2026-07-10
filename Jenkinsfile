pipeline {
    agent {
        docker {
            image 'python:3.10-slim'
            // DODALIŚMY TUTAJ: -u 0 (uruchom jako użytkownik root)
            args '--shm-size=2g -u 0'
        }
    }
    
    stages {
        stage('Instalacja zależności w agencie') {
            steps {
                sh '''
                    # 1. Sprawdzanie i instalacja pakietów systemowych APT
                    if dpkg -s libgbm1 libnss3 libatk-bridge2.0-0 libgtk-3-0 libxshmfence1 libasound2 >/dev/null 2>&1; then
                        echo ">>> Pakiety systemowe APT są już zainstalowane."
                    else
                        echo ">>> Instalacja pakietów systemowych APT..."
                        apt-get update && apt-get install -y libgbm1 libnss3 libatk-bridge2.0-0 libgtk-3-0 libxshmfence1 libasound2
                    fi
                    
                    # 2. Aktualizacja pip, setuptools i wheel
                    pip install --upgrade pip setuptools wheel
                    
                    # 3. Inteligentna instalacja bibliotek Pythona (tylko brakujące)
                    REQUIRED_PKGS="playwright beautifulsoup4 python-dotenv nltk torch transformers spacy groq google-genai pandas matplotlib seaborn reportlab"
                    INSTALL_LIST=""
                    
                    for pkg in $REQUIRED_PKGS; do
                        if pip show $pkg >/dev/null 2>&1; then
                            echo ">>> Biblioteka Pythona '$pkg' jest już zainstalowana."
                        else
                            INSTALL_LIST="$INSTALL_LIST $pkg"
                        fi
                    done
                    
                    if [ ! -z "$INSTALL_LIST" ]; then
                        echo ">>> Instalacja brakujących bibliotek:$INSTALL_LIST"
                        pip install $INSTALL_LIST
                    fi
                    
                    # 4. Sprawdzanie i pobieranie modeli/przeglądarek
                    if [ -d "/root/.cache/ms-playwright" ] && [ "$(ls -A /root/.cache/ms-playwright 2>/dev/null)" ]; then
                        echo ">>> Playwright Chromium jest już zainstalowany."
                    else
                        echo ">>> Instalacja Playwright Chromium..."
                        playwright install chromium
                    fi
                    
                    if python3 -m spacy info pl_core_news_md >/dev/null 2>&1; then
                        echo ">>> Model spaCy 'pl_core_news_md' jest już pobrany."
                    else
                        echo ">>> Pobieranie modelu spaCy 'pl_core_news_md'..."
                        python3 -m spacy download pl_core_news_md
                    fi
                    
                    if python3 -c "import os; import nltk; print(os.path.exists(os.path.expanduser('~/nltk_data/tokenizers/punkt_tab')))" 2>/dev/null | grep -q "True"; then
                        echo ">>> Pakiet NLTK 'punkt_tab' jest już pobrany."
                    else
                        echo ">>> Pobieranie pakietu NLTK 'punkt_tab'..."
                        python3 -c "import nltk; nltk.download('punkt_tab', quiet=True)"
                    fi
                '''
            }
        }

        stage('Wstrzyknięcie konfiguracji .env z GUI') {
            steps {
                // ZMIANA: używamy 'file' zamiast 'string', ponieważ 'moj-plik-env' to Secret file
                withCredentials([file(credentialsId: 'moj-plik-env', variable: 'ENV_FILE_PATH')]) {
                    sh '''
                        # 1. Kopiujemy plik konfiguracyjny do katalogu Project jako .env
                        cp "$ENV_FILE_PATH" Project/.env
                        
                        # 2. Usuwamy ukryte znaki \\r, które psują czytanie pliku w Linuxie
                        sed -i 's/\r//g' Project/.env
                        
                        # 3. Usuwamy cudzysłowy, żeby python-dotenv nie przekazywał ich do API
                        sed -i 's/"//g' Project/.env
                        
                        echo "Plik .env został poprawnie zaimportowany i sformatowany."
                    '''
                }
            }
        }
 
        stage('Uruchomienie skryptów z katalogu Project') {
            steps {
                dir('Project') {
                    sh '''
                        echo "=== KROK 1: Scraping ==="
                        python3 scrap_ceneo.py
                        
                        echo "=== KROK 2: Parsowanie HTML ==="
                        python3 parser_html_ceneo.py
                        
                        echo "=== KROK 3: Encoder ==="
                        python3 encoder_ceneo.py
                        
                        echo "=== KROK 4: Decoder ==="
                        python3 decoder_ceneo.py
                        
                        echo "=== KROK 5: Raport ==="
                        python3 generate_report_ceneo.py
                    '''
                }
            }
        }
    }
}
