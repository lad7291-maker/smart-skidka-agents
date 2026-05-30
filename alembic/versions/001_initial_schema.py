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
        sa.PrimaryKeyConstraint('id')
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
        sa.PrimaryKeyConstraint('id')
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
        sa.PrimaryKeyConstraint('id')
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
        sa.UniqueConstraint('trend_id', 'target_agent')
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
        sa.UniqueConstraint('path')
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
        sa.UniqueConstraint('path')
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
    op.create_index('idx_trend_data_sources_name', 'trend_data_sources', ['source_name'])
    op.create_index('idx_trend_recommendations_trend', 'trend_recommendations', ['trend_id'])
    op.create_index('idx_trend_recommendations_agent', 'trend_recommendations', ['target_agent'])
    op.create_index('idx_agent_pages_agent', 'agent_pages', ['agent_name'])
    op.create_index('idx_agent_pages_status', 'agent_pages', ['status'])
    op.create_index('idx_content_registry_type', 'content_registry', ['content_type'])
    op.create_index('idx_content_registry_agent', 'content_registry', ['agent_name'])


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
