pipeline {
    agent {
        docker {
            image 'python:3.10-slim'
            // ZMIANA: Zmieniliśmy mapowanie. Teraz mapujemy bezpieczny folder na cache pobierania pip oraz modele, 
            // bez dotykania wewnętrznych plików systemowych Pythona (site-packages).
            args '--shm-size=2g -u 0 -v /var/jenkins_home/pip_cache:/root/.cache/pip -v /var/jenkins_home/ms-playwright:/root/.cache/ms-playwright -v /var/jenkins_home/nltk_data:/root/nltk_data'
        }
    }
    
    stages {
        stage('Instalacja zależności w agencie') {
            steps {
                sh '''
                    echo "=== SPRAWDZANIE ŚRODOWISKA ==="

                    # 1. Sprawdzanie i instalacja pakietów systemowych APT
                    if dpkg -s libgbm1 libnss3 libatk-bridge2.0-0 libgtk-3-0 libxshmfence1 libasound2 >/dev/null 2>&1; then
                        echo ">>> [OK] Pakiety systemowe APT są już w systemie."
                    else
                        echo ">>> [BRAK] Instalacja pakietów systemowych APT..."
                        apt-get update && apt-get install -y libgbm1 libnss3 libatk-bridge2.0-0 libgtk-3-0 libxshmfence1 libasound2
                    fi
                    
                    # 2. Aktualizacja pip, setuptools i wheel
                    pip install --upgrade pip setuptools wheel
                    
                    # 3. Instalacja bibliotek Pythona (wykorzysta zmapowany cache pip_cache na VPS)
                    echo ">>> Instalacja/Weryfikacja bibliotek Pythona..."
                    pip install playwright beautifulsoup4 python-dotenv nltk torch transformers spacy groq google-genai pandas matplotlib seaborn reportlab
                    
                    # 4. Sprawdzanie i pobieranie przeglądarki Chromium dla Playwright
                    if [ -d "/root/.cache/ms-playwright/chromium-"* ]; then
                        echo ">>> [OK] Playwright Chromium jest już pobrany."
                    else
                        echo ">>> [BRAK] Pobieranie Playwright Chromium..."
                        playwright install chromium
                    fi
                    
                    # 5. Sprawdzanie i pobieranie modelu spaCy
                    if python3 -m spacy info pl_core_news_md >/dev/null 2>&1; then
                        echo ">>> [OK] Model spaCy 'pl_core_news_md' jest już na dysku."
                    else
                        echo ">>> [BRAK] Pobieranie modelu spaCy 'pl_core_news_md'..."
                        python3 -m spacy download pl_core_news_md
                    fi
                    
                    # 6. Sprawdzanie i pobieranie tokenizera NLTK
                    if python3 -c "import os; import nltk; print(os.path.exists(os.path.expanduser('~/nltk_data/tokenizers/punkt_tab')))" 2>/dev/null | grep -q "True"; then
                        echo ">>> [OK] Pakiet NLTK 'punkt_tab' jest już na dysku."
                    else
                        echo ">>> [BRAK] Pobieranie pakietu NLTK 'punkt_tab'..."
                        python3 -c "import nltk; nltk.download('punkt_tab', quiet=True)"
                    fi
                    
                    echo "=== ŚRODOWISKO ZWERYFIKOWANE I GOTOWE ==="
                '''
            }
        }

        stage('Wstrzyknięcie konfiguracji .env z GUI') {
            steps {
                withCredentials([file(credentialsId: 'moj-plik-env', variable: 'ENV_FILE_PATH')]) {
                    sh '''
                        cp "$ENV_FILE_PATH" Project/.env
                        sed -i 's/\r//g' Project/.env
                        sed -i 's/"//g' Project/.env
                        echo "Plik .env został poprawnie zaimportowany."
                    '''
                }
            }
        }

        stage('Krok 1: Scraping') {
            steps {
                dir('Project') {
                    sh 'python3 scrap_ceneo.py'
                }
            }
        }

        stage('Krok 2: Parsowanie HTML') {
            steps {
                dir('Project') {
                    sh 'python3 parser_html_ceneo.py'
                }
            }
        }

        stage('Krok 3: Encoder') {
            steps {
                dir('Project') {
                    sh 'python3 encoder_ceneo.py'
                }
            }
        }

        stage('Krok 4: Decoder') {
            steps {
                dir('Project') {
                    sh 'python3 decoder_ceneo.py'
                }
            }
        }

        stage('Krok 5: Raport') {
            steps {
                dir('Project') {
                    sh 'python3 generate_report_ceneo.py'
                }
            }
        }
    }
}
