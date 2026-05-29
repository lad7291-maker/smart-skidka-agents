-- Инициализация базы данных для smart-skidka-agents
-- Multi-agent система автономного маркетинга

-- Таблица запусков циклов
CREATE TABLE IF NOT EXISTS orchestrator_cycles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'running',
    agents_total INTEGER DEFAULT 0,
    agents_success INTEGER DEFAULT 0,
    agents_failed INTEGER DEFAULT 0,
    report JSONB
);

-- Таблица результатов агентов
CREATE TABLE IF NOT EXISTS agent_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cycle_id UUID REFERENCES orchestrator_cycles(id),
    agent_name VARCHAR(50) NOT NULL,
    task_type VARCHAR(100),
    result JSONB,
    validation_score FLOAT,
    validation_errors JSONB,
    execution_time_ms INTEGER,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Таблица метрик
CREATE TABLE IF NOT EXISTS metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name VARCHAR(50),
    metric_name VARCHAR(100) NOT NULL,
    metric_value FLOAT,
    metric_unit VARCHAR(20),
    dimensions JSONB,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Таблица ошибок
CREATE TABLE IF NOT EXISTS agent_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cycle_id UUID REFERENCES orchestrator_cycles(id),
    agent_name VARCHAR(50) NOT NULL,
    error_type VARCHAR(50),
    error_message TEXT,
    stack_trace TEXT,
    retry_count INTEGER DEFAULT 0,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Таблица памяти контекста
CREATE TABLE IF NOT EXISTS agent_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name VARCHAR(50) NOT NULL,
    context_key VARCHAR(200) NOT NULL,
    context_value JSONB,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(agent_name, context_key)
);

-- Таблица сгенерированного контента
CREATE TABLE IF NOT EXISTS generated_content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_type VARCHAR(50) NOT NULL,
    agent_name VARCHAR(50) NOT NULL,
    title VARCHAR(500),
    content_html TEXT,
    meta_description TEXT,
    keywords JSONB,
    validation_score FLOAT,
    status VARCHAR(20) DEFAULT 'draft',
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Таблица задач агентов
CREATE TABLE IF NOT EXISTS agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name VARCHAR(50) NOT NULL,
    task_name VARCHAR(200) NOT NULL,
    task_config JSONB,
    schedule_cron VARCHAR(100),
    last_run_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 5,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_agent_results_agent_name ON agent_results(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_results_cycle ON agent_results(cycle_id);
CREATE INDEX IF NOT EXISTS idx_agent_results_created ON agent_results(created_at);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_metrics_agent ON metrics(agent_name);
CREATE INDEX IF NOT EXISTS idx_metrics_recorded ON metrics(recorded_at);
CREATE INDEX IF NOT EXISTS idx_errors_agent ON agent_errors(agent_name);
CREATE INDEX IF NOT EXISTS idx_errors_resolved ON agent_errors(resolved);
CREATE INDEX IF NOT EXISTS idx_memory_agent_key ON agent_memory(agent_name, context_key);
CREATE INDEX IF NOT EXISTS idx_content_type ON generated_content(content_type);
CREATE INDEX IF NOT EXISTS idx_content_status ON generated_content(status);

-- Вставка начальных задач
INSERT INTO agent_tasks (agent_name, task_name, schedule_cron, priority) VALUES
    ('seo_agent', 'Генерация SEO-страниц', '0 */6 * * *', 3),
    ('seo_agent', 'Кластеризация ключевых слов', '0 3 * * 1', 4),
    ('seo_agent', 'Технический аудит', '0 4 * * 0', 5),
    ('smm_agent', 'Генерация постов', '0 */12 * * *', 2),
    ('smm_agent', 'Контент-план на неделю', '0 10 * * 1', 3),
    ('performance_agent', 'Генерация объявлений', '0 */6 * * *', 3),
    ('performance_agent', 'Оптимизация CPC', '0 */12 * * *', 4),
    ('performance_agent', 'A/B тесты', '0 9 * * *', 5),
    ('email_agent', 'Проверка триггеров', '0 */6 * * *', 2),
    ('email_agent', 'Дайджест', '0 10 * * 1', 3),
    ('email_agent', 'Реактивация', '0 12 * * 3', 4),
    ('analytics_agent', 'Ежедневный отчёт', '0 8 * * *', 1),
    ('analytics_agent', 'Когортный анализ', '0 6 * * 0', 4),
    ('content_agent', 'Генерация SEO-контента', '0 */6 * * *', 3),
    ('content_agent', 'Описания товаров', '0 */8 * * *', 4),
    ('content_agent', 'Сравнения и гайды', '0 14 * * 2,4,6', 5)
ON CONFLICT DO NOTHING;


-- ============================================================
-- Trend Research Agent — таблицы для анализа трендов
-- ============================================================

-- Таблица обнаруженных трендов
CREATE TABLE IF NOT EXISTS trend_detections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cycle_id UUID REFERENCES orchestrator_cycles(id),
    trend_type VARCHAR(20) CHECK (trend_type IN ('product', 'category', 'event', 'viral', 'seasonal')),
    confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    title VARCHAR(500),
    description TEXT,
    status VARCHAR(20) DEFAULT 'rising' CHECK (status IN ('rising', 'peak', 'declining')),
    data_sources JSONB, -- ["tiktok", "wildberries", "google_trends"]
    metrics JSONB, -- {"search_growth": "+240%", "sales_growth": "+340%"}
    estimated_traffic_potential VARCHAR(100),
    peak_date DATE,
    window_of_opportunity_hours INTEGER DEFAULT 48,
    competition_level VARCHAR(20) CHECK (competition_level IN ('low', 'medium', 'high')),
    recommended_actions JSONB, -- [{"agent": "seo_agent", "action": "...", "priority": "high"}]
    validated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Таблица источников данных трендов
CREATE TABLE IF NOT EXISTS trend_data_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name VARCHAR(50) NOT NULL, -- "google_trends", "wildberries", "tiktok"
    source_type VARCHAR(20), -- "search", "marketplace", "social"
    last_fetch_at TIMESTAMP WITH TIME ZONE,
    fetch_status VARCHAR(20) DEFAULT 'ok',
    fetch_error TEXT,
    data_sample JSONB, -- пример последних данных
    refresh_interval_minutes INTEGER DEFAULT 360,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Таблица рекомендаций выданных другим агентам
CREATE TABLE IF NOT EXISTS trend_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trend_id UUID REFERENCES trend_detections(id),
    target_agent VARCHAR(50) NOT NULL, -- "seo_agent", "smm_agent", etc
    action_description TEXT NOT NULL,
    priority VARCHAR(10) CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    deadline TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected', 'completed')),
    result JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE
);

-- Таблица контекста трендов для агентов (что агент уже знает)
CREATE TABLE IF NOT EXISTS agent_trend_context (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name VARCHAR(50) NOT NULL,
    trend_id UUID REFERENCES trend_detections(id),
    context_snapshot JSONB, -- что агент получил
    applied_at TIMESTAMP WITH TIME ZONE, -- когда применил
    result_score FLOAT, -- насколько хорошо сработало
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(agent_name, trend_id)
);

-- ============================================================
-- Индексы для trend-таблиц
-- ============================================================

-- Индексы для trend_detections
CREATE INDEX IF NOT EXISTS idx_trend_detections_cycle ON trend_detections(cycle_id);
CREATE INDEX IF NOT EXISTS idx_trend_detections_type ON trend_detections(trend_type);
CREATE INDEX IF NOT EXISTS idx_trend_detections_status ON trend_detections(status);
CREATE INDEX IF NOT EXISTS idx_trend_detections_confidence ON trend_detections(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_trend_detections_competition ON trend_detections(competition_level);
CREATE INDEX IF NOT EXISTS idx_trend_detections_peak_date ON trend_detections(peak_date);
CREATE INDEX IF NOT EXISTS idx_trend_detections_validated ON trend_detections(validated);
CREATE INDEX IF NOT EXISTS idx_trend_detections_created ON trend_detections(created_at DESC);

-- Индексы для trend_data_sources
CREATE INDEX IF NOT EXISTS idx_trend_data_sources_name ON trend_data_sources(source_name);
CREATE INDEX IF NOT EXISTS idx_trend_data_sources_type ON trend_data_sources(source_type);
CREATE INDEX IF NOT EXISTS idx_trend_data_sources_active ON trend_data_sources(is_active);
CREATE INDEX IF NOT EXISTS idx_trend_data_sources_fetch_status ON trend_data_sources(fetch_status);

-- Индексы для trend_recommendations
CREATE INDEX IF NOT EXISTS idx_trend_recommendations_trend ON trend_recommendations(trend_id);
CREATE INDEX IF NOT EXISTS idx_trend_recommendations_agent ON trend_recommendations(target_agent);
CREATE INDEX IF NOT EXISTS idx_trend_recommendations_priority ON trend_recommendations(priority);
CREATE INDEX IF NOT EXISTS idx_trend_recommendations_status ON trend_recommendations(status);
CREATE INDEX IF NOT EXISTS idx_trend_recommendations_created ON trend_recommendations(created_at DESC);

-- Индексы для agent_trend_context
CREATE INDEX IF NOT EXISTS idx_agent_trend_context_agent ON agent_trend_context(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_trend_context_trend ON agent_trend_context(trend_id);
CREATE INDEX IF NOT EXISTS idx_agent_trend_context_applied ON agent_trend_context(applied_at);

-- ============================================================
-- Начальные данные: источники данных трендов
-- ============================================================

INSERT INTO trend_data_sources (source_name, source_type, refresh_interval_minutes, is_active) VALUES
    ('google_trends', 'search', 360, TRUE),
    ('yandex_wordstat', 'search', 360, TRUE),
    ('wildberries', 'marketplace', 180, TRUE),
    ('ozon', 'marketplace', 180, TRUE),
    ('vk', 'social', 120, TRUE),
    ('telegram', 'social', 120, TRUE),
    ('tiktok', 'social', 60, TRUE),
    ('pikabu', 'social', 240, TRUE),
    ('news', 'social', 120, TRUE)
ON CONFLICT DO NOTHING;

-- ============================================================
-- Начальные данные: задачи trend_agent
-- ============================================================

INSERT INTO agent_tasks (agent_name, task_name, schedule_cron, priority) VALUES
    ('trend_agent', 'Сканирование трендов (все источники)', '0 */3 * * *', 1),
    ('trend_agent', 'Анализ вирусного контента', '0 */6 * * *', 2),
    ('trend_agent', 'Оценка сезонности', '0 6 * * *', 3),
    ('trend_agent', 'Формирование рекомендаций агентам', '0 */6 * * *', 2),
    ('trend_agent', 'Валидация обнаруженных трендов', '0 9 * * *', 2),
    ('trend_agent', 'Прогноз пика тренда', '0 12 * * *', 3)
ON CONFLICT DO NOTHING;
