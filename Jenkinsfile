pipeline {
    agent {
        dockerfile {
            filename 'Dockerfile.agent'
            // Używamy ${WORKSPACE}, aby precyzyjnie wskazać katalog roboczy potoku wewnątrz agenta
            args '--shm-size=2g -u 0 -v /var/data/huggingface_cache:${WORKSPACE}/Project/models'
        }
    }

    parameters {
        string(
            name: 'CENEO_PRODUCT_ID', 
            defaultValue: '', 
            description: 'Wpisz ręcznie ID produktu, aby nadpisać wartość z pliku .env. Zostaw puste, aby użyć domyślnej.'
        )
    }
    
    stages {
        stage('Wstrzyknięcie konfiguracji .env z GUI') {
            steps {
                withCredentials([file(credentialsId: 'moj-plik-env', variable: 'ENV_FILE_PATH')]) {
                    withEnv(["CENEO_PRODUCT_ID=${params.CENEO_PRODUCT_ID}"]) {
                        sh '''
                            # 1. Kopiujemy domyślny plik .env
                            cp "$ENV_FILE_PATH" Project/.env
                            sed -i 's/\r//g' Project/.env
                            sed -i 's/"//g' Project/.env
                            
                            # 2. SPRAWDZAMY PARAMETR Z GUI JENKINSA:
                            if [ ! -z "$CENEO_PRODUCT_ID" ]; then
                                echo "Wykryto ręczne nadpisanie z GUI: $CENEO_PRODUCT_ID"
                                sed -i '/^CENEO_PRODUCT_ID=/d' Project/.env
                                echo "CENEO_PRODUCT_ID=$CENEO_PRODUCT_ID" >> Project/.env
                                echo "Pomyślnie nadpisano CENEO_PRODUCT_ID wartością z GUI."
                            else
                                echo "Pole GUI puste. Używam domyślnej konfiguracji z pliku .env."
                            fi

                            echo "Plik .env został poprawnie zaimportowany i przygotowany."
                        '''
                    }
                }
            }
        }

        stage('Krok 1: Scraping') { steps { dir('Project') { sh 'python3 scrap_ceneo.py' } } }
        stage('Krok 2: Parsowanie HTML') { steps { dir('Project') { sh 'python3 parser_html_ceneo.py' } } }
        stage('Krok 3: Encoder') { steps { dir('Project') { sh 'python3 encoder_ceneo.py' } } }
        stage('Krok 4: Decoder') { steps { dir('Project') { sh 'python3 decoder_ceneo.py' } } }
        stage('Krok 5: Raport') { steps { dir('Project') { sh 'python3 generate_report_ceneo.py' } } }
    }
}
