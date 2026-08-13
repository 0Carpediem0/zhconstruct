$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Host "Docker CLI was not found. Install Docker Desktop and run this script again." -ForegroundColor Red
  exit 1
}

try {
  docker info *> $null
} catch {
  Write-Host "Docker Desktop is not running. Open Docker Desktop, wait for Running status, then run this script again." -ForegroundColor Yellow
  exit 1
}

if (-not (Test-Path -LiteralPath ".env")) {
  Copy-Item -LiteralPath ".env.example" -Destination ".env"
  Write-Host "Created local .env from .env.example"
}

Write-Host "Building and starting PostgreSQL + Django..."
docker compose up -d --build

Write-Host "Applying migrations..."
docker compose exec backend python manage.py migrate

Write-Host "Creating demo data..."
docker compose exec backend python manage.py seed_demo_data `
  --admin-password Admin2026! `
  --demo-password DemoUser2026!

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Resident portal: http://localhost:8000/app/login/"
Write-Host "AI chat after login: http://localhost:8000/app/ai-chat/"
Write-Host "Django Admin: http://localhost:8000/admin/"
Write-Host ""
Write-Host "Resident: demo-resident / DemoUser2026!"
Write-Host "Admin: admin / Admin2026!"

