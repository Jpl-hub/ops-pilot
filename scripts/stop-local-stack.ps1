$ErrorActionPreference = "Stop"

docker compose stop postgres api ui
docker compose -f docker-compose.streaming.yml stop
