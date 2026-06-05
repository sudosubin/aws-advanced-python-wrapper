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

from __future__ import annotations

import psycopg
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg

from aws_advanced_python_wrapper import AwsWrapperConnection
from aws_advanced_python_wrapper.errors import FailoverError


class SqlAlchemyOrmPgDialect(PGDialect_psycopg):
    """
    SQLAlchemy dialect for the AWS Advanced Python Wrapper with psycopg, selected via the
    "postgresql+aws_wrapper_psycopg://" URL scheme.

    The overrides below unwrap to target_connection (the real psycopg connection) wherever the
    parent dialect touches psycopg-only attributes that AwsWrapperConnection does not expose.
    """

    name = 'postgresql'
    driver = 'aws_wrapper_psycopg'
    supports_statement_cache = True

    # hstore registration calls TypeInfo.fetch on driver_connection, which the wrapper hides.
    use_native_hstore = False

    def __init__(self, **kwargs):
        # Validate version / build adapters against real psycopg, then route connect via the wrapper.
        wrapper_dbapi = kwargs.get('dbapi')
        if wrapper_dbapi is not None:
            kwargs['dbapi'] = psycopg
        super().__init__(**kwargs)
        if wrapper_dbapi is not None:
            self.dbapi = wrapper_dbapi

    @classmethod
    def import_dbapi(cls):
        import aws_advanced_python_wrapper
        return aws_advanced_python_wrapper

    def create_connect_args(self, url):
        cargs, cparams = super().create_connect_args(url)

        cparams['target'] = psycopg.Connection.connect
        if 'wrapper_plugins' not in cparams:
            cparams['plugins'] = "aurora_connection_tracker,failover_v2,host_monitoring_v2"
        else:
            cparams['plugins'] = cparams['wrapper_plugins']
            cparams.pop('wrapper_plugins', None)
        if 'connect_timeout' in cparams:
            cparams['connect_timeout'] = int(cparams['connect_timeout'])

        return [], cparams

    def do_ping(self, dbapi_connection) -> bool:
        # Ping the real connection (the wrapper has no ping()); False invalidates the pool.
        try:
            return super().do_ping(self._target_connection(dbapi_connection))
        except psycopg.Error:
            return False

    def is_disconnect(self, e, connection, cursor) -> bool:
        if isinstance(e, FailoverError):
            return True
        if connection is not None:
            target = self._target_connection(connection)
            return bool(getattr(target, 'closed', False) or getattr(target, 'broken', False))
        return False

    def get_isolation_level(self, dbapi_connection):
        return super().get_isolation_level(self._target_connection(dbapi_connection))

    def _do_isolation_level(self, connection, autocommit, isolation_level):
        # autocommit via the wrapper survives failover; isolation_level (psycopg-only) does not.
        connection.autocommit = autocommit
        self._target_connection(connection).isolation_level = isolation_level

    def on_connect(self):
        # Drop the parent's add_notice_handler call (not on the wrapper); keep isolation setup.
        if self.isolation_level is None:
            return None

        def connect(conn):
            self.set_isolation_level(conn, self.isolation_level)

        return connect

    @staticmethod
    def _target_connection(dbapi_connection):
        if isinstance(dbapi_connection, AwsWrapperConnection):
            return dbapi_connection.target_connection
        return dbapi_connection
