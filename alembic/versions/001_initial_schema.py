"""
Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-30 18:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Seed data
# ═══════════════════════════════════════════════════════════════════════════════

def _seed_agent_tasks():
    """Начальные задачи агентов."""
    return [
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
        ('content_agent', 'Сравнения и гайды', '0 14 * * 2,4,6', 5),
        ('trend_agent', 'Сканирование трендов (все источники)', '0 */3 * * *', 1),
        ('trend_agent', 'Анализ вирусного контента', '0 */6 * * *', 2),
        ('trend_agent', 'Оценка сезонности', '0 6 * * *', 3),
        ('trend_agent', 'Формирование рекомендаций агентам', '0 */6 * * *', 2),
        ('trend_agent', 'Валидация обнаруженных трендов', '0 9 * * *', 2),
        ('trend_agent', 'Прогноз пика тренда', '0 12 * * *', 3),
    ]


def _seed_trend_data_sources():
    """Начальные источники данных трендов."""
    return [
        ('google_trends', 'search', 360, True),
        ('yandex_wordstat', 'search', 360, True),
        ('wildberries', 'marketplace', 180, True),
        ('ozon', 'marketplace', 180, True),
        ('vk', 'social', 120, True),
        ('telegram', 'social', 120, True),
        ('tiktok', 'social', 60, True),
        ('pikabu', 'social', 240, True),
        ('news', 'social', 120, True),
    ]


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════════════
    # Core tables
    # ═══════════════════════════════════════════════════════════════════════
    op.create_table(
        'orchestrator_cycles',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), server_default='running', nullable=True),
        sa.Column('agents_total', sa.Integer, server_default='0', nullable=True),
        sa.Column('agents_success', sa.Integer, server_default='0', nullable=True),
        sa.Column('agents_failed', sa.Integer, server_default='0', nullable=True),
        sa.Column('report', postgresql.JSONB, nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'agent_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('cycle_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('agent_name', sa.String(50), nullable=False),
        sa.Column('task_type', sa.String(100), nullable=True),
        sa.Column('result', postgresql.JSONB, nullable=True),
        sa.Column('validation_score', sa.Float, nullable=True),
        sa.Column('validation_errors', postgresql.JSONB, nullable=True),
        sa.Column('execution_time_ms', sa.Integer, nullable=True),
        sa.Column('status', sa.String(20), server_default='pending', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['cycle_id'], ['orchestrator_cycles.id'], ondelete='SET NULL')
    )

    op.create_table(
        'metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('agent_name', sa.String(50), nullable=True),
        sa.Column('metric_name', sa.String(100), nullable=False),
        sa.Column('metric_value', sa.Float, nullable=True),
        sa.Column('metric_unit', sa.String(20), nullable=True),
        sa.Column('dimensions', postgresql.JSONB, nullable=True),
        sa.Column('recorded_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'agent_errors',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('cycle_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('agent_name', sa.String(50), nullable=False),
        sa.Column('error_type', sa.String(50), nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('stack_trace', sa.Text, nullable=True),
        sa.Column('retry_count', sa.Integer, server_default='0', nullable=True),
        sa.Column('resolved', sa.Boolean, server_default='FALSE', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['cycle_id'], ['orchestrator_cycles.id'], ondelete='SET NULL')
    )

    op.create_table(
        'agent_memory',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('agent_name', sa.String(50), nullable=False),
        sa.Column('context_key', sa.String(200), nullable=False),
        sa.Column('context_value', postgresql.JSONB, nullable=True),
        sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_name', 'context_key')
    )

    op.create_table(
        'generated_content',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('content_type', sa.String(50), nullable=False),
        sa.Column('agent_name', sa.String(50), nullable=False),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('content_html', sa.Text, nullable=True),
        sa.Column('meta_description', sa.Text, nullable=True),
        sa.Column('keywords', postgresql.JSONB, nullable=True),
        sa.Column('validation_score', sa.Float, nullable=True),
        sa.Column('status', sa.String(20), server_default='draft', nullable=True),
        sa.Column('published_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'agent_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('agent_name', sa.String(50), nullable=False),
        sa.Column('task_name', sa.String(200), nullable=False),
        sa.Column('task_config', postgresql.JSONB, nullable=True),
        sa.Column('schedule_cron', sa.String(100), nullable=True),
        sa.Column('last_run_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean, server_default='TRUE', nullable=True),
        sa.Column('priority', sa.Integer, server_default='5', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_name', 'task_name')
    )

    # ═══════════════════════════════════════════════════════════════════════
    # Trend tables
    # ═══════════════════════════════════════════════════════════════════════
    op.create_table(
        'trend_detections',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('cycle_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('trend_type', sa.String(20), nullable=True),
        sa.Column('confidence', sa.Float, nullable=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('status', sa.String(20), server_default='rising', nullable=True),
        sa.Column('data_sources', postgresql.JSONB, nullable=True),
        sa.Column('metrics', postgresql.JSONB, nullable=True),
        sa.Column('estimated_traffic_potential', sa.String(100), nullable=True),
        sa.Column('peak_date', sa.Date, nullable=True),
        sa.Column('window_of_opportunity_hours', sa.Integer, server_default='48', nullable=True),
        sa.Column('competition_level', sa.String(20), nullable=True),
        sa.Column('recommended_actions', postgresql.JSONB, nullable=True),
        sa.Column('validated', sa.Boolean, server_default='FALSE', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['cycle_id'], ['orchestrator_cycles.id'], ondelete='SET NULL'),
        sa.CheckConstraint("trend_type IN ('product', 'category', 'event', 'viral', 'seasonal')", name='ck_trend_type'),
        sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name='ck_confidence'),
        sa.CheckConstraint("status IN ('rising', 'peak', 'declining')", name='ck_trend_status'),
        sa.CheckConstraint("competition_level IN ('low', 'medium', 'high')", name='ck_competition_level'),
    )

    op.create_table(
        'trend_data_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('source_name', sa.String(50), nullable=False),
        sa.Column('source_type', sa.String(20), nullable=True),
        sa.Column('last_fetch_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('fetch_status', sa.String(20), server_default='ok', nullable=True),
        sa.Column('fetch_error', sa.Text, nullable=True),
        sa.Column('data_sample', postgresql.JSONB, nullable=True),
        sa.Column('refresh_interval_minutes', sa.Integer, server_default='360', nullable=True),
        sa.Column('is_active', sa.Boolean, server_default='TRUE', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'trend_recommendations',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('trend_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('target_agent', sa.String(50), nullable=False),
        sa.Column('action_description', sa.Text, nullable=False),
        sa.Column('priority', sa.String(10), nullable=True),
        sa.Column('deadline', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending', nullable=True),
        sa.Column('result', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.Column('resolved_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['trend_id'], ['trend_detections.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('trend_id', 'target_agent'),
        sa.CheckConstraint("priority IN ('low', 'medium', 'high', 'critical')", name='ck_priority'),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'completed')", name='ck_rec_status'),
    )

    op.create_table(
        'agent_trend_context',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('agent_name', sa.String(50), nullable=False),
        sa.Column('trend_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('context_snapshot', postgresql.JSONB, nullable=True),
        sa.Column('applied_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('result_score', sa.Float, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['trend_id'], ['trend_detections.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('agent_name', 'trend_id')
    )

    # ═══════════════════════════════════════════════════════════════════════
    # Pages & content registry
    # ═══════════════════════════════════════════════════════════════════════
    op.create_table(
        'agent_pages',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('path', sa.String(500), nullable=False),
        sa.Column('agent_name', sa.String(50), nullable=False),
        sa.Column('page_type', sa.String(50), nullable=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('status', sa.String(20), server_default='active', nullable=True),
        sa.Column('http_status', sa.Integer, nullable=True),
        sa.Column('html_valid', sa.Boolean, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.Column('last_checked_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('path'),
        sa.CheckConstraint("status IN ('active', 'deprecated', 'error')", name='ck_page_status'),
    )

    op.create_table(
        'content_registry',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('content_type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('slug', sa.String(200), nullable=False),
        sa.Column('path', sa.String(500), nullable=False),
        sa.Column('agent_name', sa.String(50), nullable=False),
        sa.Column('keywords', postgresql.JSONB, nullable=True),
        sa.Column('related_slugs', postgresql.JSONB, nullable=True),
        sa.Column('status', sa.String(20), server_default='published', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
        sa.UniqueConstraint('path'),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name='ck_content_status'),
    )

    # ═══════════════════════════════════════════════════════════════════════
    # Indexes
    # ═══════════════════════════════════════════════════════════════════════
    op.create_index('idx_agent_results_agent_name', 'agent_results', ['agent_name'])
    op.create_index('idx_agent_results_cycle', 'agent_results', ['cycle_id'])
    op.create_index('idx_agent_results_created', 'agent_results', ['created_at'])
    op.create_index('idx_metrics_name', 'metrics', ['metric_name'])
    op.create_index('idx_metrics_agent', 'metrics', ['agent_name'])
    op.create_index('idx_metrics_recorded', 'metrics', ['recorded_at'])
    op.create_index('idx_errors_agent', 'agent_errors', ['agent_name'])
    op.create_index('idx_errors_resolved', 'agent_errors', ['resolved'])
    op.create_index('idx_memory_agent_key', 'agent_memory', ['agent_name', 'context_key'])
    op.create_index('idx_content_type', 'generated_content', ['content_type'])
    op.create_index('idx_content_status', 'generated_content', ['status'])
    op.create_index('idx_trend_detections_cycle', 'trend_detections', ['cycle_id'])
    op.create_index('idx_trend_detections_type', 'trend_detections', ['trend_type'])
    op.create_index('idx_trend_detections_status', 'trend_detections', ['status'])
    op.create_index('idx_trend_detections_confidence', 'trend_detections', ['confidence'])
    op.create_index('idx_trend_detections_created', 'trend_detections', ['created_at'])
    op.create_index('idx_trend_detections_competition', 'trend_detections', ['competition_level'])
    op.create_index('idx_trend_detections_peak_date', 'trend_detections', ['peak_date'])
    op.create_index('idx_trend_detections_validated', 'trend_detections', ['validated'])
    op.create_index('idx_trend_data_sources_name', 'trend_data_sources', ['source_name'])
    op.create_index('idx_trend_data_sources_type', 'trend_data_sources', ['source_type'])
    op.create_index('idx_trend_data_sources_active', 'trend_data_sources', ['is_active'])
    op.create_index('idx_trend_data_sources_fetch_status', 'trend_data_sources', ['fetch_status'])
    op.create_index('idx_trend_recommendations_trend', 'trend_recommendations', ['trend_id'])
    op.create_index('idx_trend_recommendations_agent', 'trend_recommendations', ['target_agent'])
    op.create_index('idx_trend_recommendations_priority', 'trend_recommendations', ['priority'])
    op.create_index('idx_trend_recommendations_status', 'trend_recommendations', ['status'])
    op.create_index('idx_trend_recommendations_created', 'trend_recommendations', ['created_at'])
    op.create_index('idx_agent_pages_agent', 'agent_pages', ['agent_name'])
    op.create_index('idx_agent_pages_status', 'agent_pages', ['status'])
    op.create_index('idx_agent_pages_type', 'agent_pages', ['page_type'])
    op.create_index('idx_content_registry_type', 'content_registry', ['content_type'])
    op.create_index('idx_content_registry_agent', 'content_registry', ['agent_name'])
    op.create_index('idx_content_registry_status', 'content_registry', ['status'])

    # ═══════════════════════════════════════════════════════════════════════════════
    # Seed data via bulk_insert
    # ═══════════════════════════════════════════════════════════════════════════════
    op.bulk_insert(
        sa.table(
            'agent_tasks',
            sa.column('agent_name', sa.String(50)),
            sa.column('task_name', sa.String(200)),
            sa.column('schedule_cron', sa.String(100)),
            sa.column('priority', sa.Integer),
        ),
        [
            {'agent_name': r[0], 'task_name': r[1], 'schedule_cron': r[2], 'priority': r[3]}
            for r in _seed_agent_tasks()
        ],
    )

    op.bulk_insert(
        sa.table(
            'trend_data_sources',
            sa.column('source_name', sa.String(50)),
            sa.column('source_type', sa.String(20)),
            sa.column('refresh_interval_minutes', sa.Integer),
            sa.column('is_active', sa.Boolean),
        ),
        [
            {'source_name': r[0], 'source_type': r[1], 'refresh_interval_minutes': r[2], 'is_active': r[3]}
            for r in _seed_trend_data_sources()
        ],
    )


def downgrade() -> None:
    # Drop in reverse order
    op.drop_index('idx_content_registry_agent', 'content_registry')
    op.drop_index('idx_content_registry_type', 'content_registry')
    op.drop_index('idx_agent_pages_status', 'agent_pages')
    op.drop_index('idx_agent_pages_agent', 'agent_pages')
    op.drop_index('idx_trend_recommendations_agent', 'trend_recommendations')
    op.drop_index('idx_trend_recommendations_trend', 'trend_recommendations')
    op.drop_index('idx_trend_data_sources_name', 'trend_data_sources')
    op.drop_index('idx_trend_detections_created', 'trend_detections')
    op.drop_index('idx_trend_detections_confidence', 'trend_detections')
    op.drop_index('idx_trend_detections_status', 'trend_detections')
    op.drop_index('idx_trend_detections_type', 'trend_detections')
    op.drop_index('idx_trend_detections_cycle', 'trend_detections')
    op.drop_index('idx_content_status', 'generated_content')
    op.drop_index('idx_content_type', 'generated_content')
    op.drop_index('idx_memory_agent_key', 'agent_memory')
    op.drop_index('idx_errors_resolved', 'agent_errors')
    op.drop_index('idx_errors_agent', 'agent_errors')
    op.drop_index('idx_metrics_recorded', 'metrics')
    op.drop_index('idx_metrics_agent', 'metrics')
    op.drop_index('idx_metrics_name', 'metrics')
    op.drop_index('idx_agent_results_created', 'agent_results')
    op.drop_index('idx_agent_results_cycle', 'agent_results')
    op.drop_index('idx_agent_results_agent_name', 'agent_results')

    op.drop_table('content_registry')
    op.drop_table('agent_pages')
    op.drop_table('agent_trend_context')
    op.drop_table('trend_recommendations')
    op.drop_table('trend_data_sources')
    op.drop_table('trend_detections')
    op.drop_table('agent_tasks')
    op.drop_table('generated_content')
    op.drop_table('agent_memory')
    op.drop_table('agent_errors')
    op.drop_table('metrics')
    op.drop_table('agent_results')
    op.drop_table('orchestrator_cycles')
