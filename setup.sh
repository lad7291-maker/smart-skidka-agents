#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# setup.sh — Автоматическая установка smart-skidka-agents
# Multi-agent система автономного маркетинга
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PROJECT_DIR="/opt/smart-skidka-agents"
LOG_FILE="/tmp/smart-skidka-setup.log"

# ─── Helpers ──────────────────────────────────────────────────────────────────
log()   { echo -e "${GREEN}[$(date '+%H:%M:%S')] $1${NC}" | tee -a "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠ $1${NC}" | tee -a "$LOG_FILE"; }
error() { echo -e "${RED}[$(date '+%H:%M:%S')] ✖ $1${NC}" | tee -a "$LOG_FILE"; exit 1; }
info()  { echo -e "${BLUE}[$(date '+%H:%M:%S')] ℹ $1${NC}" | tee -a "$LOG_FILE"; }

# ─── Проверка root ────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    error "Запустите скрипт от root: sudo bash setup.sh"
fi

# ─── Приветствие ──────────────────────────────────────────────────────────────
clear
cat << 'EOF'
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║   ███████╗███╗   ███╗ █████╗ ██████╗ ████████╗    ███████╗██╗  ██╗██╗██████╗  ║
║   ██╔════╝████╗ ████║██╔══██╗██╔══██╗╚══██╔══╝    ██╔════╝██║ ██╔╝██║██╔══██╗ ║
║   ███████╗██╔████╔██║███████║██████╔╝   ██║       ███████╗█████╔╝ ██║██║  ██║ ║
║   ╚════██║██║╚██╔╝██║██╔══██║██╔══██╗   ██║       ╚════██║██╔═██╗ ██║██║  ██║ ║
║   ███████║██║ ╚═╝ ██║██║  ██║██║  ██║   ██║       ███████║██║  ██╗██║██████╔╝ ║
║   ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝       ╚══════╝╚═╝  ╚═╝╚═╝╚═════╝  ║
║                                                                               ║
║              Multi-Agent Система Автономного Маркетинга                       ║
║                      smart-skidka.ru                                          ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
EOF

info "Лог установки: $LOG_FILE"
echo

# ═══════════════════════════════════════════════════════════════════════════════
# ШАГ 1: Обновление системы
# ═══════════════════════════════════════════════════════════════════════════════
log "=== Шаг 1/10: Обновление системы ==="
apt-get update -qq && apt-get upgrade -y -qq | tee -a "$LOG_FILE"
log "✓ Система обновлена"

# ═══════════════════════════════════════════════════════════════════════════════
# ШАГ 2: Установка зависимостей
# ═══════════════════════════════════════════════════════════════════════════════
log "=== Шаг 2/10: Установка зависимостей ==="
apt-get install -y -qq \
    curl \
    wget \
    git \
    htop \
    mc \
    nano \
    ca-certificates \
    gnupg \
    lsb-release \
    jq \
    fail2ban \
    ufw \
    | tee -a "$LOG_FILE"
log "✓ Зависимости установлены"

# ═══════════════════════════════════════════════════════════════════════════════
# ШАГ 3: Настройка часового пояса
# ═══════════════════════════════════════════════════════════════════════════════
log "=== Шаг 3/10: Настройка часового пояса ==="
timedatectl set-timezone Europe/Moscow
log "✓ Часовой пояс: $(timedatectl | grep 'Time zone')"

# ═══════════════════════════════════════════════════════════════════════════════
# ШАГ 4: Установка Docker
# ═══════════════════════════════════════════════════════════════════════════════
log "=== Шаг 4/10: Установка Docker ==="
if command -v docker &> /dev/null; then
    info "Docker уже установлен: $(docker --version)"
else
    curl -fsSL https://get.docker.com | sh | tee -a "$LOG_FILE"
    systemctl enable docker
    systemctl start docker
    usermod -aG docker root
    log "✓ Docker установлен: $(docker --version)"
fi

# Docker Compose Plugin
if docker compose version &> /dev/null; then
    info "Docker Compose уже установлен: $(docker compose version)"
else
    apt-get install -y -qq docker-compose-plugin | tee -a "$LOG_FILE"
    log "✓ Docker Compose установлен"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# ШАГ 5: Настройка фаервола
# ═══════════════════════════════════════════════════════════════════════════════
log "=== Шаг 5/10: Настройка UFW фаервола ==="
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw --force enable
log "✓ UFW включен. Открыт только SSH (порт 22)"

# ═══════════════════════════════════════════════════════════════════════════════
# ШАГ 6: Создание директории проекта
# ═══════════════════════════════════════════════════════════════════════════════
log "=== Шаг 6/10: Создание директории проекта ==="
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"
log "✓ Директория создана: $PROJECT_DIR"

# ═══════════════════════════════════════════════════════════════════════════════
# ШАГ 7: Копирование файлов
# ═══════════════════════════════════════════════════════════════════════════════
log "=== Шаг 7/10: Копирование файлов ==="

# Проверяем откуда запущен скрипт
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
    # Файлы рядом со скриптом
    cp -r "$SCRIPT_DIR"/* "$PROJECT_DIR/"
    log "✓ Файлы скопированы из $SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/assets/docker-compose.yml" ]; then
    # Структура с assets/
    cp -r "$SCRIPT_DIR"/* "$PROJECT_DIR/"
    log "✓ Файлы скопированы из $SCRIPT_DIR"
else
    warn "Файлы проекта не найдят рядом со скриптом"
    info "Пожалуйста, скопируйте файлы вручную:"
    info "  cp -r ./smart-skidka-agents/* $PROJECT_DIR/"
    read -p "Нажмите Enter после копирования..."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# ШАГ 8: Настройка .env
# ═══════════════════════════════════════════════════════════════════════════════
log "=== Шаг 8/10: Настройка .env ==="

if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    fi
fi

cat << 'ENVEOF'

═══════════════════════════════════════════════════════════════════════════════
                    ⚠  НАСТРОЙКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
═══════════════════════════════════════════════════════════════════════════════

Вам нужно заполнить файл .env следующими значениями:

  1. LLM_API_KEY      — API ключ от RouterAI или DeepSeek
  2. TELEGRAM_BOT_TOKEN — токен бота (получить у @BotFather)
  3. TELEGRAM_CHAT_ID   — ваш chat_id (узнать через @userinfobot)

Команды для получения:
  • Bot токен:  откройте @BotFather в Telegram → /newbot → введите имя
  • Chat ID:    откройте @userinfobot в Telegram → скопируйте число
  • API ключ:   зарегистрируйтесь на rrouter.ai → API Keys

ENVEOF

read -p "Нажмите Enter чтобы открыть .env в редакторе nano..."
nano "$PROJECT_DIR/.env"

# Проверка что .env заполнен
if grep -q "your_" "$PROJECT_DIR/.env" 2>/dev/null; then
    warn "Файл .env содержит placeholder-значения (your_*)!"
    warn "Система запустится, но агенты не будут работать корректно."
    read -p "Продолжить anyway? (y/N): " CONTINUE
    if [[ ! "$CONTINUE" =~ ^[Yy]$ ]]; then
        info "Отредактируйте $PROJECT_DIR/.env и запустите: cd $PROJECT_DIR && docker compose up -d"
        exit 0
    fi
fi

chmod 600 "$PROJECT_DIR/.env"
log "✓ .env настроен и защищен (chmod 600)"

# ═══════════════════════════════════════════════════════════════════════════════
# ШАГ 9: Запуск системы
# ═══════════════════════════════════════════════════════════════════════════════
log "=== Шаг 9/10: Запуск Docker Compose ==="
cd "$PROJECT_DIR"

# Проверяем наличие docker-compose.yml
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ] && [ -f "$PROJECT_DIR/assets/docker-compose.yml" ]; then
    ln -sf "$PROJECT_DIR/assets/docker-compose.yml" "$PROJECT_DIR/docker-compose.yml"
fi

docker compose pull 2>/dev/null || true
docker compose build --no-cache | tee -a "$LOG_FILE"
docker compose up -d | tee -a "$LOG_FILE"

sleep 5

# Проверка статуса
RUNNING=$(docker compose ps --format json 2>/dev/null | jq -r '.[].State' 2>/dev/null | grep -c "running" || echo "0")
if [ "$RUNNING" -ge 2 ]; then
    log "✓ Контейнеры запущены ($RUNNING сервисов)"
else
    warn "Запущено менее 2 сервисов. Проверьте логи: docker compose logs"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# ШАГ 10: Проверка работоспособности
# ═══════════════════════════════════════════════════════════════════════════════
log "=== Шаг 10/10: Проверка работоспособности ==="

echo
info "Статус контейнеров:"
docker compose ps | tee -a "$LOG_FILE"

echo
info "Проверка PostgreSQL:"
docker compose exec -T postgres pg_isready -U agents 2>/dev/null && log "✓ PostgreSQL отвечает" || warn "PostgreSQL не отвечает"

echo
info "Проверка Redis:"
docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q "PONG" && log "✓ Redis отвечает" || warn "Redis не отвечает"

echo
info "Последние логи оркестратора:"
docker compose logs --tail=20 orchestrator 2>/dev/null || warn "Оркестратор ещё не создал логов"

# ═══════════════════════════════════════════════════════════════════════════════
# ФИНАЛ
# ═══════════════════════════════════════════════════════════════════════════════
echo
cat << EOF
${GREEN}
╔═══════════════════════════════════════════════════════════════════════════════╗
║                     ✅ УСТАНОВКА ЗАВЕРШЕНА!                                 ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  📁 Директория:    $PROJECT_DIR                             ║
║  📋 Лог установки: $LOG_FILE                                    ║
║                                                                               ║
║  🚀 Быстрые команды:                                                          ║
║     cd $PROJECT_DIR                                                           ║
║     docker compose ps                    # статус контейнеров                 ║
║     docker compose logs -f orchestrator  # логи оркестратора                  ║
║     docker compose logs -f telegram-bot  # логи Telegram бота                 ║
║     docker compose restart               # перезапуск всех сервисов           ║
║     docker compose down                  # остановка                          ║
║                                                                               ║
║  💬 Telegram бот:                                                             ║
║     Отправьте /start вашему боту для проверки                                 ║
║                                                                               ║
║  📖 Документация:                                                             ║
║     cat $PROJECT_DIR/DEPLOY.md                                                ║
║     cat $PROJECT_DIR/SKILL.md                                                 ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
${NC}
EOF
