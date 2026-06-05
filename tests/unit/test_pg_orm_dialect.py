#  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License").
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import psycopg
import pytest
from sqlalchemy.engine.url import make_url

import aws_advanced_python_wrapper
from aws_advanced_python_wrapper import AwsWrapperConnection
from aws_advanced_python_wrapper.errors import (AwsWrapperError,
                                                FailoverSuccessError)
from aws_advanced_python_wrapper.sqlalchemy.pg_orm_dialect import \
    SqlAlchemyOrmPgDialect


@pytest.fixture
def dialect():
    return SqlAlchemyOrmPgDialect(dbapi=aws_advanced_python_wrapper)


@pytest.fixture
def dbapi_connection(mocker):
    connection = mocker.MagicMock(spec=AwsWrapperConnection)
    connection.target_connection = mocker.MagicMock()
    return connection


def test_init_routes_connect_through_wrapper(dialect):
    # dbapi is the wrapper (connect routing), but version / adapters come from real psycopg.
    assert dialect.dbapi is aws_advanced_python_wrapper
    assert dialect.psycopg_version >= (3, 0, 2)
    assert dialect._psycopg_adapters_map is not None


def test_create_connect_args_injects_target_and_plugins(dialect):
    url = make_url("postgresql+aws_wrapper_psycopg://u:p@host:5432/db?connect_timeout=10")

    cargs, cparams = dialect.create_connect_args(url)

    assert cargs == []
    assert cparams["target"] == psycopg.Connection.connect
    assert cparams["plugins"] == "aurora_connection_tracker,failover_v2,host_monitoring_v2"
    assert cparams["connect_timeout"] == 10  # cast from the str URL query to int
    assert (cparams["host"], cparams["dbname"], cparams["user"]) == ("host", "db", "u")


def test_create_connect_args_renames_wrapper_plugins(dialect):
    url = make_url("postgresql+aws_wrapper_psycopg://u:p@host/db?wrapper_plugins=failover_v2")

    _, cparams = dialect.create_connect_args(url)

    assert cparams["plugins"] == "failover_v2"
    assert "wrapper_plugins" not in cparams


def test_do_ping_pings_wrapped_target_connection(dialect, dbapi_connection):
    assert dialect.do_ping(dbapi_connection) is True
    dbapi_connection.target_connection.cursor.assert_called_once()


def test_do_ping_returns_false_on_dead_connection(dialect, dbapi_connection):
    dbapi_connection.target_connection.cursor.side_effect = psycopg.OperationalError("connection closed")
    assert dialect.do_ping(dbapi_connection) is False


def test_is_disconnect_true_on_failover(dialect, dbapi_connection):
    assert dialect.is_disconnect(FailoverSuccessError(), dbapi_connection, None) is True


def test_is_disconnect_true_when_target_closed(dialect, dbapi_connection):
    dbapi_connection.target_connection.closed = True
    dbapi_connection.target_connection.broken = False
    assert dialect.is_disconnect(AwsWrapperError(), dbapi_connection, None) is True


def test_is_disconnect_false_on_healthy_connection(dialect, dbapi_connection):
    dbapi_connection.target_connection.closed = False
    dbapi_connection.target_connection.broken = False
    assert dialect.is_disconnect(AwsWrapperError(), dbapi_connection, None) is False
