"""add chat sessions

Revision ID: 9c0f0f0b8d0e
Revises: 5f45e1b6d7a1
Create Date: 2026-03-27 11:20:13.345622

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c0f0f0b8d0e"
down_revision: Union[str, Sequence[str], None] = "5f45e1b6d7a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_session",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="Primary key.",
        ),
        sa.Column(
            "title",
            sa.String(length=120),
            nullable=False,
            comment="Human-readable session title.",
        ),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="Chat session creation date.",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_session_user_id"), "chat_session", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_chat_session_created_at"),
        "chat_session",
        ["created_at"],
        unique=False,
    )

    op.add_column("chat_history", sa.Column("session_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_chat_history_session_id_chat_session",
        "chat_history",
        "chat_session",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_chat_history_session_id"),
        "chat_history",
        ["session_id"],
        unique=False,
    )

    op.execute(
        """
        UPDATE chat_history AS ch
        SET user_id = ak.owner_id
        FROM api_key AS ak
        WHERE ch.user_id IS NULL
          AND ch.api_key_id = ak.id
        """
    )

    op.execute(
        """
        INSERT INTO chat_session (user_id, title, created_at)
        SELECT
            ch.user_id,
            'Legacy imported session',
            MIN(ch.created_at)
        FROM chat_history AS ch
        GROUP BY ch.user_id
        """
    )

    op.execute(
        """
        UPDATE chat_history AS ch
        SET session_id = cs.id
        FROM chat_session AS cs
        WHERE cs.title = 'Legacy imported session'
          AND (
              ch.user_id = cs.user_id
              OR (ch.user_id IS NULL AND cs.user_id IS NULL)
          )
        """
    )

    op.alter_column("chat_history", "session_id", nullable=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_history_session_id"), table_name="chat_history")
    op.drop_constraint(
        "fk_chat_history_session_id_chat_session",
        "chat_history",
        type_="foreignkey",
    )
    op.drop_column("chat_history", "session_id")

    op.drop_index(op.f("ix_chat_session_created_at"), table_name="chat_session")
    op.drop_index(op.f("ix_chat_session_user_id"), table_name="chat_session")
    op.drop_table("chat_session")
