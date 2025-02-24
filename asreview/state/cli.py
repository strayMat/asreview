# Copyright 2019-2022 The ASReview Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
from pathlib import Path

import pandas as pd

from asreview.project import get_project_path
from asreview.state.contextmanager import open_state


def _parse_state_inspect_args():
    # parse arguments if available
    parser = argparse.ArgumentParser(
        prog="state-inspect", description="Inspect state file."
    )
    parser.add_argument(
        "project_id", type=str, help="Project_id or path to ASReview file."
    )
    parser.add_argument(
        "table",
        type=str,
        help="Table to view (e.g. results, record_table, last_ranking).",
    )

    return parser


def cli_state_inspect(argv):
    parser = _parse_state_inspect_args()
    args = parser.parse_args(argv)

    if Path(args.project_id).suffix == ".asreview":
        project_path = args.project_id
    else:
        project_path = get_project_path(args.project_id)

    with open_state(project_path) as s:
        conn = s._conn()

        df = pd.read_sql(f"select * from {args.table}", conn)

    if args.table == "results":
        df["label"] = df["label"].astype(pd.Int64Dtype())

    print(f"Table '{args.table}':\n")
    print(df)
    print("\n")
