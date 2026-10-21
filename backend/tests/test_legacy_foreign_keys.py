"""Удаления в базе, созданной старыми миграциями: внешние ключи без каскадов (NO ACTION).

В таких базах (например, у разработчика) SQLite не удалит строку, на которую что-то
ссылается, поэтому каждый путь удаления обязан убирать зависимые строки сам.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base, Campaign, Client, DeliveryTask, School, SchoolClass
from app.routers import campaigns, clients, schools
from app.schemas import CampaignDeleteIn, ClientDeleteIn


@contextmanager
def _without_fk_actions():
    foreign_keys = [fk for table in Base.metadata.tables.values() for fk in table.foreign_keys]
    saved = [(fk, fk.ondelete, fk.constraint.ondelete) for fk in foreign_keys]
    for fk in foreign_keys:
        fk.ondelete = fk.constraint.ondelete = None
    try:
        yield
    finally:
        for fk, ondelete, constraint_ondelete in saved:
            fk.ondelete, fk.constraint.ondelete = ondelete, constraint_ondelete


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    with _without_fk_actions():
        Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    for module in (schools, clients, campaigns):
        monkeypatch.setattr(module, "session_scope", scope)

    with scope() as session:
        school = School(name="Школа")
        session.add(school)
        session.flush()
        klass = SchoolClass(school_id=school.id, name="5А")
        session.add(klass)
        session.flush()
        contact = Client(name="Иванова", school_id=school.id, class_id=klass.id)
        session.add(contact)
        session.flush()
        campaign = Campaign(name="Собрание", message="Текст", school_id=school.id)
        session.add(campaign)
        session.flush()
        session.add(
            DeliveryTask(campaign_id=campaign.id, client_id=contact.id, rendered_message="x")
        )
        session.commit()
        ids = {
            "school": school.id,
            "klass": klass.id,
            "contact": contact.id,
            "campaign": campaign.id,
        }
    return scope, ids


def _count(scope, model):
    with scope() as session:
        return session.query(model).count()


def test_delete_school_keeps_its_campaigns(legacy):
    scope, ids = legacy
    schools.delete_school(ids["school"])
    assert _count(scope, School) == 0
    assert _count(scope, SchoolClass) == 0
    assert _count(scope, Client) == 0
    assert _count(scope, DeliveryTask) == 0
    with scope() as session:
        campaign = session.get(Campaign, ids["campaign"])
        assert campaign is not None and campaign.school_id is None


def test_delete_class(legacy):
    scope, ids = legacy
    schools.delete_class(ids["klass"])
    assert _count(scope, SchoolClass) == 0 and _count(scope, Client) == 0
    assert _count(scope, School) == 1


def test_delete_client_and_bulk(legacy):
    scope, ids = legacy
    clients.delete_client(ids["contact"])
    assert _count(scope, Client) == 0 and _count(scope, DeliveryTask) == 0


def test_bulk_delete_clients(legacy):
    scope, ids = legacy
    assert clients.delete_clients(ClientDeleteIn(client_ids=[ids["contact"]])) == {"deleted": 1}
    assert _count(scope, DeliveryTask) == 0


def test_delete_campaign_and_bulk(legacy):
    scope, ids = legacy
    campaigns.delete_campaign(ids["campaign"])
    assert _count(scope, Campaign) == 0 and _count(scope, DeliveryTask) == 0


def test_bulk_delete_campaigns(legacy):
    scope, ids = legacy
    result = campaigns.delete_campaigns(CampaignDeleteIn(campaign_ids=[ids["campaign"]]))
    assert result == {"deleted": 1}
    assert _count(scope, DeliveryTask) == 0
