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

from typing import Any

import django.db.backends.postgresql.base as base
import django.db.backends.postgresql.operations as operations
import psycopg
from django.core.exceptions import ImproperlyConfigured
from django.db.backends.postgresql.psycopg_any import (IsolationLevel, mogrify,
                                                       register_tzloader)
from django.utils.asyncio import async_unsafe
from psycopg.pq import Format

from aws_advanced_python_wrapper import AwsWrapperConnection


class DatabaseOperations(operations.DatabaseOperations):
    def last_executed_query(self, cursor, sql, params):
        # Unwrap to the psycopg cursor; Django reads its _query attribute.
        target_cursor = getattr(cursor, "target_cursor", cursor)
        return super().last_executed_query(target_cursor, sql, params)

    def compose_sql(self, sql, params):
        # mogrify builds a psycopg ClientCursor, so pass the psycopg connection.
        return mogrify(sql, params, self.connection.connection.target_connection)


class DatabaseWrapper(base.DatabaseWrapper):
    """Custom PostgreSQL backend for Django"""

    ops_class = DatabaseOperations

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._read_only = False

    @async_unsafe
    def get_new_connection(self, conn_params):
        options = self.settings_dict["OPTIONS"]
        set_isolation_level = False
        try:
            isolation_level_value = options["isolation_level"]
        except KeyError:
            self.isolation_level = IsolationLevel.READ_COMMITTED
        else:
            try:
                self.isolation_level = IsolationLevel(isolation_level_value)
                set_isolation_level = True
            except ValueError:
                raise ImproperlyConfigured(
                    f"Invalid transaction isolation level {isolation_level_value} "
                    f"specified. Use one of the psycopg.IsolationLevel values."
                )

        conn = AwsWrapperConnection.connect(psycopg.Connection.connect, **conn_params)

        if set_isolation_level:
            conn.target_connection.isolation_level = self.isolation_level
        if self._read_only:
            conn.read_only = True
        return conn

    def get_connection_params(self):
        kwargs = super().get_connection_params()
        self._read_only = kwargs.pop("read_only", False)
        return kwargs

    @async_unsafe
    def create_cursor(self, name=None):
        if not name:
            return super().create_cursor(name)

        # Server-side cursors need the raw psycopg connection, so they bypass
        # the plugin pipeline (only client-side cursors are wrapped).
        target_connection = self.connection.target_connection
        if self.settings_dict["OPTIONS"].get("server_side_binding") is not True:
            cursor = base.ServerSideCursor(
                target_connection, name=name, scrollable=False, withhold=self.connection.autocommit
            )
        else:
            cursor = target_connection.cursor(
                name, scrollable=False, withhold=self.connection.autocommit
            )

        tzloader = self.connection.adapters.get_loader(base.TIMESTAMPTZ_OID, Format.TEXT)
        if self.timezone != tzloader.timezone:
            register_tzloader(self.timezone, cursor)
        return cursor
