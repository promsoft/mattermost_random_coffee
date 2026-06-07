import pytest
from sqlalchemy.exc import IntegrityError

from coffeebot.db.models import Base, User, UserState
from coffeebot.db.session import make_engine, make_session_factory


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        yield session


def test_user_defaults(session):
    user = User(mm_user_id="abc123", username="ivan")
    session.add(user)
    session.commit()

    saved = session.get(User, user.id)
    assert saved.state == UserState.ACTIVE
    assert saved.unmatched_streak == 0
    assert saved.profile is None
    assert saved.created_at is not None


def test_mm_user_id_unique(session):
    session.add(User(mm_user_id="dup", username="first"))
    session.commit()
    session.add(User(mm_user_id="dup", username="second"))
    with pytest.raises(IntegrityError):
        session.commit()
