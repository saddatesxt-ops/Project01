pipeline {
    agent {
        docker {
            image 'python:3.10-slim'
            // Przekazujemy zamapowane foldery z dysku VPS, aby zachować cache środowiska
            args '--shm-size=2g -u 0 -v /var/jenkins_home/python_packages:/usr/local/lib/python3.10/site-packages -v /var/jenkins_home/ms-playwright:/root/.cache/ms-playwright -v /var/jenkins_home/nltk_data:/root/nltk_data'
        }
    }
    
    stages {
        stage('Instalacja zależności w agencie') {
            steps {
                sh '''
                    echo "=== SPRAWDZANIE ŚRODOWISKA ==="
                    if dpkg -s libgbm1 libnss3 libatk-bridge2.0-0 libgtk-3-0 libxshmfence1 libasound2 >/dev/null 2>&1; then
                        echo ">>> [OK] Pakiety systemowe APT są już w systemie."
                    else
                        echo ">>> [BRAK] Instalacja pakietów systemowych APT..."
                        apt-get update && apt-get install -y libgbm1 libnss3 libatk-bridge2.0-0 libgtk-3-0 libxshmfence1 libasound2
                    fi
                    
                    pip install --upgrade pip setuptools wheel
                    
                    REQUIRED_PKGS="playwright beautifulsoup4 python-dotenv nltk torch transformers spacy groq google-genai pandas matplotlib seaborn reportlab"
                    INSTALL_LIST=""
                    for pkg in $REQUIRED_PKGS; do
                        if pip show $pkg >/dev/null 2>&1; then
                            echo ">>> [OK] Biblioteka Pythona '$pkg' jest już zainstalowana."
                        else
                            INSTALL_LIST="$INSTALL_LIST $pkg"
                        fi
                    done
                    
                    if [ ! -z "$INSTALL_LIST" ]; then
                        echo ">>> Instalacja brakujących bibliotek:$INSTALL_LIST"
                        pip install $INSTALL_LIST
                    fi
                    
                    if [ -d "/root/.cache/ms-playwright/chromium-"* ]; then
                        echo ">>> [OK] Playwright Chromium jest już pobrany."
                    else
                        playwright install chromium
                    fi
                    
                    if python3 -m spacy info pl_core_news_md >/dev/null 2>&1; then
                        echo ">>> [OK] Model spaCy 'pl_core_news_md' jest już na dysku."
                    else
                        python3 -m spacy download pl_core_news_md
                    fi
                    
                    if python3 -c "import os; import nltk; print(os.path.exists(os.path.expanduser('~/nltk_data/tokenizers/punkt_tab')))" 2>/dev/null | grep -q "True"; then
                        echo ">>> [OK] Pakiet NLTK 'punkt_tab' jest już na dysku."
                    else
                        python3 -c "import nltk; nltk.download('punkt_tab', quiet=True)"
                    fi
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

        // --- ROZBICIE URUCHAMIANIA NA ODDZIELNE ETAPY (VISIBLE IN PIPELINE OVERVIEW) ---

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
