pipeline {
    agent {
        dockerfile {
            // Jenkins sam znajdzie ten plik w pobranym z Gita kodzie i zbuduje kontener!
            filename 'Dockerfile.agent'
            args '--shm-size=2g -u 0'
        }
    }
    
    stages {
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
