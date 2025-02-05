#  Copyright (c) 2022. Harvard University
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

"""
This module is a command line tool to introspect and ingest into a database
a directory, containing CSV (or CSV-like, e.g. FST, JSON, SAS, etc.) files.
The directory can be structured, e.g. have nested subdirectories. All files
matching a certain name pattern at any nested subdirectory level
are included in the data set.

In the database, a schema is crated based on the given project name.
For each file in the data set a table is created. The name
of the table is constructed from the relative path of the
incoming data file with OS path separators (e.g. '/') being
replaced with underscores ('_').
"""

import logging
import os
from pathlib import PurePath

import yaml

from nsaph.data_model.domain import Domain
from nsaph.loader import LoaderConfig
from nsaph.loader.data_loader import DataLoader
from nsaph.loader.introspector import Introspector


def is_relative_to(p: PurePath, *other):
    """Return True if the path is relative to another path or False.
    """
    try:
        p.relative_to(*other)
        return True
    except ValueError:
        return False


def remove_ext(p: str) -> str:
    d, f = os.path.split(p)
    pos = f.find('.')
    if pos >= 0:
        return os.path.join(d, f[:pos])
    return os.path.join(d, f)


class ProjectLoader(DataLoader):
    @classmethod
    def new_domain(cls, name: str, file_path: str):
        domain = dict()
        domain[name] = dict()
        d = domain[name]
        d["schema"] = name
        d["header"] = True
        d["quoting"] = 0
        d["index"] = "unless excluded"
        d["tables"] = dict()
        with open(file_path, "wt") as f:
            yaml.dump(domain, f, indent=2)

    def __init__(self, context: LoaderConfig = None):
        """
        Class, implementing Project Loading functionality.

        :param context: Configuration options, usually provided as command
            line arguments
        """

        if not context:
            context = LoaderConfig(__doc__).instantiate()
        if context.registry is not None and not os.path.exists(context.registry):
            self.new_domain(context.domain, context.registry)
        super().__init__(context)
        with open(context.registry) as f:
            self.registry = yaml.safe_load(f)
        return

    def introspect(self, entry: str):
        p = PurePath(entry)
        table = None
        for root in self.context.data:
            if is_relative_to(p, root):
                relpath = PurePath(os.path.relpath(remove_ext(entry), root))
                table = "_".join(relpath.parts)
        if table is None:
            raise ValueError(entry)

        introspector = Introspector(entry)
        introspector.lines_to_load = 20000
        introspector.introspect()
        introspector.append_file_column()
        introspector.append_record_column()
        columns = introspector.get_columns()
        self.registry[self.domain.domain]["tables"][table] = {
            "columns": columns,
            "primary_key": [
                "FILE",
                "RECORD"
            ]
        }
        return table

    def save_registry(self):
        with open(self.context.registry, "wt") as f:
            yaml.dump(self.registry, f)
            f.write('\n')
        self.domain = Domain(self.registry, self.domain.domain)
        self.domain.init()
        return 

    def run(self):
        """
        Run introspection and ingestion.

        :return: nothing
        """

        entries = self.get_files()
        tables = {
            self.introspect(entry[0]): entry[0]
            for entry in entries
        }
        self.save_registry()
        if self.context.dryrun:
            return
        inputs = self.context.data
        s = 0
        e = 0
        for table in tables:
            self.set_table(table)
            self.context.data = [tables[table]]
            self.reset()
            try:
                self.load()
                s += 1
            except:
                self.drop()
                logging.exception("Failed to load data into table " + table)
                e += 1
        self.context.data = inputs
        logging.info(
            "All done. Tables loaded: {:d}, tables failed: {:d}.".format(s, e)
        )
        return


if __name__ == '__main__':
    loader = ProjectLoader()
    loader.run()
