"""create rl_trajectories table — Unified System

Revision ID: 118
Revises: 117
Create Date: 2026-06-06

Adds ``rl_trajectories`` to the enterprise schema.  Each row represents one
RL episode (= one OpenHands conversation) initiated by OpenManus-RL.  The
table is used for offline analysis and reward debugging; it is *not* on the
critical path of the training loop (all writes are best-effort).

Schema
------
rl_trajectories
    conversation_id   PK, FK → conversation_metadata.conversation_id
    task_description  TEXT     natural-language task sent at episode start
    metadata          TEXT     JSON blob with extra RL context (task_idx, …)
    steps             INTEGER  number of agent turns in this episode
    final_reward      FLOAT    scalar reward at episode end (0.0 – 1.0)
    crew_id           TEXT     crewAI Crew identifier that generated the action
    created_at        DATETIME episode start timestamp
    updated_at        DATETIME last step timestamp
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "118"
down_revision: Union[str, None] = "117"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rl_trajectories",
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey(
                "conversation_metadata.conversation_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("task_description", sa.Text(), nullable=False),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("final_reward", sa.Float(), nullable=True),
        sa.Column("crew_id", sa.String(), nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("conversation_id"),
    )

    # Index for analytics queries: reward distribution per crew
    op.create_index(
        "ix_rl_trajectories_crew_reward",
        "rl_trajectories",
        ["crew_id", "final_reward"],
    )


def downgrade() -> None:
    op.drop_index("ix_rl_trajectories_crew_reward", table_name="rl_trajectories")
    op.drop_table("rl_trajectories")
