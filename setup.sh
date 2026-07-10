#!/bin/bash
set -e

echo "============================================="
echo "   KROK 1: Instalacja Dockera na serwerze    "
echo "============================================="

if ! command -v docker &> /dev/null; then
    echo "Docker nie jest zainstalowany. Rozpoczynam instalację..."
    sudo apt-get update
    sudo apt-get install -y curl gnupg lsb-release
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
      
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    echo "[OK] Docker został pomyślnie zainstalowany."
else
    echo "[OK] Docker jest już zainstalowany na tym serwerze."
fi

echo "============================================="
echo "   KROK 2: Budowanie obrazu Jenkinsa         "
echo "============================================="
# Budujemy obraz z klientem docker-cli w środku
docker build -t moj-custom-jenkins:latest -f Dockerfile.jenkins .

echo "============================================="
echo "   KROK 3: Uruchamianie kontenera Jenkins    "
echo "============================================="

# Sprawdzamy czy kontener o tej nazwie już istnieje i go usuwamy
if [ "$(docker ps -aq -f name=jenkins-server)" ]; then
    echo "Usuwanie starego kontenera jenkins-server..."
    docker rm -f jenkins-server
fi

# Uruchomienie Jenkinsa. 
# Mapujemy /var/run/docker.sock, żeby Jenkins mógł zarządzać Dockerem na hoście.
# Mapujemy wolumen jenkins_home, żeby konfiguracja (w tym Twoje klucze .env z GUI) nie zginęła po restarcie kontenera.
docker run -d \
  --name jenkins-server \
  -p 8080:8080 \
  -p 50000:50000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v jenkins_home:/var/central/jenkins_home \
  --restart unless-stopped \
  moj-custom-jenkins:latest

echo "============================================="
echo "   PROCES INICJALIZACJI ZAKOŃCZONY SUKCESEM  "
echo "============================================="
echo "Jenkins jest uruchamiany. Poczekaj chwilę i wejdź na: http://<IP_SERWERA>:8080"
echo "Aby pobrać hasło początkowe roota, wpisz w konsoli serwera:"
echo "docker logs jenkins-server"
echo "============================================="