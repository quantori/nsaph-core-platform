#  Copyright (c) 2021. Harvard University
#
#  Developed by Research Software Engineering,
#  Faculty of Arts and Sciences, Research Computing (FAS RC)
#  Author: Michael A Bouzinier
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import glob
import logging
import os
import threading
import time
from abc import ABC
from pathlib import Path

import sys
from typing import Iterable, Callable

from nsaph_utils.utils.io_utils import is_yaml_or_json, is_dir
from psycopg2.extensions import connection

from nsaph import init_logging
from nsaph.data_model.domain import Domain
from nsaph.loader.common import CommonConfig
from nsaph.db import Connection
from nsaph.loader.loader_config import LoaderConfig
from nsaph.loader.monitor import DBActivityMonitor


def diff(files: Iterable[str]) -> bool:
    ff = list(files)
    for i in range(len(ff) - 1):
        ret = os.system("diff {} {}".format(ff[i], ff[i+1]))
        if ret != 0:
            return False
    return True


class LoaderBase(ABC):
    """
    Base class for tools responsible for data loading and processing
    """

    @staticmethod
    def get_domain(name: str, registry: str = None) -> Domain:
        src = None
        registry_path = None
        if registry:
            if is_yaml_or_json(registry):
                registry_path = registry
                if not os.path.isfile(registry_path):
                    raise ValueError("{} - is not a file".format(registry_path))
            elif not is_dir(registry):
                raise ValueError("{} - is not a valid registry path".format(registry))
            elif os.path.isdir(registry):
                src = registry
            else:
                raise NotImplementedError("Not Implemented: registry in an archive")
        if not src:
            src = Path(__file__).parents[3]
        if not registry_path:
            registry_path = os.path.join(src, "yml", name + ".yaml")
        if not os.path.isfile(registry_path):
            files = set()
            for d in sys.path:
                files.update(glob.glob(
                    os.path.join(d, "**", name + ".yaml"),
                    recursive=True
                ))
            if not files:
                raise ValueError("File {} not found".format(name + ".yaml"))
            if len(files) > 1:
                if not diff(files):
                    raise ValueError("Ambiguous files {}".format(';'.join(files)))
            registry_path = files.pop()
        if not os.path.isfile(registry_path):
            raise ValueError("File {} does not exist".format(os.path.abspath(registry_path)))
        domain = Domain(registry_path, name)
        return domain

    def __init__(self, context: LoaderConfig):
        init_logging()
        self.context = None
        self.domain = self.get_domain(context.domain, context.registry)
        if isinstance(context, LoaderConfig) and context.sloppy:
            self.domain.set_sloppy()
        self.domain.init()
        self.table = context.table
        self.monitor = DBActivityMonitor(context)

    def _connect(self) -> connection:
        c = Connection(self.context.db, self.context.connection).connect()
        if self.context.autocommit is not None:
            c.autocommit = self.context.autocommit
        return c

    def get_pid(self, connxn: connection) -> int:
        with connxn.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            for row in cursor:
                return row[0]

    def execute_with_monitor(self, what: Callable,
                             connxn: connection = None,
                             on_monitor: Callable = None):
        if not on_monitor:
            pid = self.get_pid(connxn)
            on_monitor = lambda: self.log_activity(pid)
        x = threading.Thread(target=what)
        x.start()
        n = 0
        step = 100
        while x.is_alive():
            time.sleep(0.1)
            n += 1
            if (n % step) == 0:
                on_monitor()
                if n > 100000:
                    step = 6000
                elif n > 10000:
                    step = 600
        x.join()

    def log_activity(self, pid: int):
        activity = self.monitor.get_activity(pid)
        for msg in activity:
            logging.info(msg)

