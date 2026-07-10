pipeline {
    agent {
        docker {
            // Kontener-agent, który ma już w sobie Pythona, Playwrighta i biblioteki
            // Zbuduje się automatycznie lub pobierze z rejestru
            image 'python:3.10-slim'
            args '--shm-size=2g'
        }
    }
    
    stages {
        stage('Instalacja zależności w agencie') {
            steps {
                sh '''
                    # Instalacja bibliotek systemowych dla Playwright w locie
                    apt-get update && apt-get install -y libgbm1 libnss3 libatk-bridge2.0-0 libgtk-3-0 libxshmfence1 libasound2
                    
                    # Instalacja bibliotek z PyPI
                    pip install --upgrade pip setuptools wheel
                    pip install playwright beautifulsoup4 python-dotenv nltk torch transformers spacy groq google-genai pandas matplotlib seaborn reportlab
                    
                    # Pobranie modeli
                    playwright install chromium
                    python3 -m spacy download pl_core_news_md
                    python3 -c "import nltk; nltk.download('punkt_tab', quiet=True)"
                '''
            }
        }

        stage('Wstrzyknięcie konfiguracji .env z GUI') {
            steps {
                // Dokładnie tak jak chciałeś: wpisujesz dane w GUI Jenkinsa (Credentials jako Secret Text o ID 'moj-plik-env')
                withCredentials([string(credentialsId: 'moj-plik-env', variable: 'ENV_CONTENT')]) {
                    // Jenkins tworzy plik .env wewnątrz katalogu Project
                    sh 'echo "$ENV_CONTENT" > Project/.env'
                }
            }
        }
 
        stage('Uruchomienie skryptów z katalogu Project') {
            steps {
                // Przechodzimy do katalogu Project i odpalamy Twoje skrypty Pythona
                dir('Project') {
                    sh '''
                        echo "=== KROK 1: Scraping ==="
                        python3 scrap_ceneo.py
                        
                        echo "=== KROK 2: Parsowanie HTML ==="
                        python3 parser_html_ceneo.py
                        
                        echo "=== KROK 3: Encoder ==="
                        python3 api_ceneo_encoder.py
                        
                        echo "=== KROK 4: Decoder ==="
                        python3 api_ceneo_decoder.py
                        
                        echo "=== KROK 5: Raport ==="
                        python3 generate_report_ceneo.py
                    '''
                }
            }
        }
    }
}