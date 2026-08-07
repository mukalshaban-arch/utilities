import pytest

from app import create_app
from app.extensions import db as _db
from config import TestConfig
from app.models import User, UtilityType, Beneficiary, Meter


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return _db


def make_user(db, name, email, password, role):
    user = User(name=name, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def make_utility_type(db, name="Power"):
    utility_type = UtilityType(name=name)
    db.session.add(utility_type)
    db.session.commit()
    return utility_type


def make_beneficiary(db, name="Jane Doe", position="Director", facility=None):
    beneficiary = Beneficiary(name=name, position=position, facility=facility)
    db.session.add(beneficiary)
    db.session.commit()
    return beneficiary


def make_meter(db, beneficiary, utility_type, number):
    meter = Meter(beneficiary_id=beneficiary.id, utility_type_id=utility_type.id, number=number)
    db.session.add(meter)
    db.session.commit()
    return meter


def login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)
