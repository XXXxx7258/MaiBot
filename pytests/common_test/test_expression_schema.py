"""测试表达方式表结构和基础插入行为。"""

from typing import Generator

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.common.database.database_model import Expression


@pytest.fixture(name="expression_engine")
def expression_engine_fixture() -> Generator:
    """创建仅用于表达方式表测试的内存数据库引擎。

    Yields:
        Generator: 供测试使用的 SQLite 内存引擎。
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine


def test_expression_insert_assigns_auto_increment_id(expression_engine) -> None:
    """表达方式表在新库中应能自动分配自增主键。"""
    with Session(expression_engine) as session:
        expression = Expression(
            situation="表达情绪高涨或生理反应",
            style="发送💦表情符号",
            content_list='["表达情绪高涨或生理反应"]',
            count=1,
            session_id="session-a",
            checked=False,
        )
        session.add(expression)
        session.commit()
        session.refresh(expression)

    assert expression.id is not None
    assert expression.id > 0


def test_expression_insert_allows_same_situation_style(expression_engine) -> None:
    """相同情景和风格的表达方式记录不应再被错误绑定到复合主键。"""
    with Session(expression_engine) as session:
        first_expression = Expression(
            situation="对重复行为的默契响应",
            style="持续性跟发相同内容",
            content_list='["对重复行为的默契响应"]',
            count=1,
            session_id="session-a",
            checked=False,
        )
        second_expression = Expression(
            situation="对重复行为的默契响应",
            style="持续性跟发相同内容",
            content_list='["对重复行为的默契响应-变体"]',
            count=2,
            session_id="session-b",
            checked=False,
        )

        session.add(first_expression)
        session.add(second_expression)
        session.commit()
        session.refresh(first_expression)
        session.refresh(second_expression)

    assert first_expression.id is not None
    assert second_expression.id is not None
    assert first_expression.id != second_expression.id
