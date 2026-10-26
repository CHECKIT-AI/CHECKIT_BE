from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.main import create_app


class FakeConnection:
    def __init__(self, role="checkit_backend", failure=False):
        self.role, self.failure = role, failure

    def execute(self, query):
        if self.failure:
            raise RuntimeError("postgresql://private-user:private-password@private-host/db")
        return self

    def fetchone(self):
        return dict(name=self.role, rolsuper=False, rolbypassrls=False,
                    rolcreaterole=False, rolcreatedb=False)


class FakePool:
    def __init__(self, connection):
        self.conn = connection
        self.closed = False

    def open(self):
        pass

    def close(self):
        self.closed = True

    @contextmanager
    def connection(self):
        yield self.conn


def test_ready_and_pool_cleanup():
    pool = FakePool(FakeConnection())
    with TestClient(create_app(pool=pool)) as client:
        assert client.get("/health/ready").status_code == 200
    assert pool.closed


def test_database_failure_does_not_disclose_secrets():
    with TestClient(create_app(pool=FakePool(FakeConnection(failure=True)))) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert "private-" not in response.text
        assert client.get("/health/live").status_code == 200


def test_owner_connection_is_not_accepted():
    with TestClient(create_app(pool=FakePool(FakeConnection(role="postgres")))) as client:
        assert client.get("/health/ready").status_code == 503
