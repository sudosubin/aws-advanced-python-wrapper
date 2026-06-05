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

from unittest.mock import MagicMock, patch

import psycopg  # type: ignore
import pytest  # type: ignore
from django.core.exceptions import ImproperlyConfigured  # type: ignore
from django.db.backends.postgresql.psycopg_any import \
    IsolationLevel  # type: ignore

CONNECT_PATH = 'aws_advanced_python_wrapper.django.backends.postgresql.base.AwsWrapperConnection.connect'
SERVER_SIDE_CURSOR_PATH = 'aws_advanced_python_wrapper.django.backends.postgresql.base.base.ServerSideCursor'


class TestDatabaseWrapper:
    """Unit tests for Django PostgreSQL DatabaseWrapper"""

    @pytest.fixture
    def database_wrapper(self):
        from aws_advanced_python_wrapper.django.backends.postgresql.base import \
            DatabaseWrapper
        wrapper = DatabaseWrapper.__new__(DatabaseWrapper)
        wrapper._read_only = False
        wrapper.settings_dict = {'OPTIONS': {}}
        return wrapper

    @pytest.fixture
    def mock_connect(self):
        with patch(CONNECT_PATH) as mock:
            mock.return_value = MagicMock()
            yield mock

    def test_get_connection_params_extracts_read_only(self, database_wrapper):
        with patch('django.db.backends.postgresql.base.DatabaseWrapper.get_connection_params', return_value={
            'host': 'localhost',
            'read_only': True
        }):
            result = database_wrapper.get_connection_params()

            assert database_wrapper._read_only is True
            assert 'read_only' not in result

    def test_get_new_connection_wraps_psycopg_with_all_params(self, mock_connect, database_wrapper):
        """get_new_connection wraps psycopg.Connection.connect and forwards every param verbatim"""
        conn_params = {'host': 'localhost', 'dbname': 'test_db', 'plugins': 'failover,aurora_connection_tracker'}
        result = database_wrapper.get_new_connection(conn_params)

        assert mock_connect.call_args.args[0] == psycopg.Connection.connect
        assert mock_connect.call_args.kwargs == conn_params
        assert result is mock_connect.return_value
        assert database_wrapper.isolation_level == IsolationLevel.READ_COMMITTED

    def test_get_new_connection_sets_read_only_when_true(self, mock_connect, database_wrapper):
        database_wrapper._read_only = True

        result = database_wrapper.get_new_connection({'host': 'localhost'})

        assert result.read_only is True

    def test_get_new_connection_applies_isolation_level_from_options(self, mock_connect, database_wrapper):
        database_wrapper.settings_dict = {'OPTIONS': {'isolation_level': IsolationLevel.SERIALIZABLE}}

        database_wrapper.get_new_connection({'host': 'localhost'})

        assert database_wrapper.isolation_level == IsolationLevel.SERIALIZABLE
        assert mock_connect.return_value.target_connection.isolation_level == IsolationLevel.SERIALIZABLE

    def test_get_new_connection_rejects_invalid_isolation_level(self, mock_connect, database_wrapper):
        database_wrapper.settings_dict = {'OPTIONS': {'isolation_level': 999}}

        with pytest.raises(ImproperlyConfigured, match="Invalid transaction isolation level"):
            database_wrapper.get_new_connection({'host': 'localhost'})

        mock_connect.assert_not_called()

    def test_create_cursor_unnamed_delegates_to_super(self, database_wrapper):
        """Unnamed cursors use the wrapper's plugin-aware cursor path"""
        sentinel = MagicMock()
        with patch('django.db.backends.postgresql.base.DatabaseWrapper.create_cursor', return_value=sentinel) as mock_super:
            result = database_wrapper.create_cursor()

            mock_super.assert_called_once_with(None)
            assert result is sentinel

    @patch(SERVER_SIDE_CURSOR_PATH)
    def test_create_cursor_named_uses_target_connection(self, mock_server_side_cursor, database_wrapper):
        """Named cursors are created on the underlying psycopg connection"""
        wrapper_connection = MagicMock()
        wrapper_connection.autocommit = True
        wrapper_connection.adapters.get_loader.return_value.timezone = 'UTC'
        database_wrapper.connection = wrapper_connection
        database_wrapper.timezone = 'UTC'

        result = database_wrapper.create_cursor('my_cursor')

        mock_server_side_cursor.assert_called_once_with(
            wrapper_connection.target_connection, name='my_cursor', scrollable=False, withhold=True
        )
        assert result is mock_server_side_cursor.return_value
