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
"""Simulation entry point and utils."""

import argparse
import logging
import re
import shutil
from pathlib import Path
from uuid import uuid4

from asreview import load_dataset
from asreview.config import DEFAULT_BALANCE_STRATEGY
from asreview.config import DEFAULT_FEATURE_EXTRACTION
from asreview.config import DEFAULT_CLASSIFIER
from asreview.config import DEFAULT_N_INSTANCES
from asreview.config import DEFAULT_N_PRIOR_EXCLUDED
from asreview.config import DEFAULT_N_PRIOR_INCLUDED
from asreview.config import DEFAULT_QUERY_STRATEGY
from asreview.datasets import DatasetManager
from asreview.models.balance.utils import get_balance_model
from asreview.models.classifiers import get_classifier
from asreview.models.feature_extraction import get_feature_model
from asreview.models.query import get_query_model
from asreview.project import Project
from asreview.project import ProjectExistsError
from asreview.settings import ReviewSettings
from asreview.simulation import Simulate
from asreview.state.contextmanager import open_state
from asreview.state import SQLiteState
from asreview.types import type_n_queries
from asreview.utils import format_to_str
from asreview.utils import get_random_state


def _set_log_verbosity(verbose):
    if verbose == 0:
        logging.getLogger().setLevel(logging.WARNING)
    elif verbose == 1:
        logging.getLogger().setLevel(logging.INFO)
    elif verbose >= 2:
        logging.getLogger().setLevel(logging.DEBUG)


def _convert_id_to_idx(data_obj, record_id):
    """Convert record_id to row number."""

    inv_record_id = dict(zip(data_obj.df.index.tolist(), range(len(data_obj))))

    result = []
    for i in record_id:
        try:
            result.append(inv_record_id[i])
        except KeyError:
            raise KeyError(f"record_id {i} not found in data.")

    return result


def _unpack_params(params):
    if params is None:
        return {}

    return params


def _print_record(record, use_cli_colors=True):
    """Format one record for displaying in the CLI.

    Arguments
    ---------
    record: Record
        The record to format.
    use_cli_colors: bool
        Some terminals support colors, set to True to use them.

    Returns
    -------
    str:
        A string including title, abstracts and authors.
    """
    if record.title is not None:
        title = record.title
        if use_cli_colors:
            title = "\033[95m" + title + "\033[0m"
        title += "\n"
    else:
        title = ""

    if record.authors is not None and len(record.authors) > 0:
        authors = format_to_str(record.authors) + "\n"
    else:
        authors = ""

    if record.abstract is not None and len(record.abstract) > 0:
        abstract = record.abstract
        abstract = "\n" + abstract + "\n"
    else:
        abstract = ""

    if record.included == 0:
        label = "IRRELEVANT"
    elif record.included == 1:
        label = "RELEVANT"
    else:
        label = ""

    header = f"---{record.record_id}---{label}---"

    print(f"\n{header:-<60}\n{title}{authors}{abstract}")


def cli_simulate(argv):
    # parse arguments
    parser = _simulate_parser()
    args = parser.parse_args(argv)

    # change the verbosity
    _set_log_verbosity(args.verbose)

    # check for state file extension
    if args.state_file is None:
        raise ValueError("Specify project file name (with .asreview extension).")

    # do this check now and again when zipping.
    if Path(args.state_file).exists():
        raise ProjectExistsError("Project already exists.")

    # create a project file
    fp_tmp_simulation = Path(args.state_file).with_suffix(".asreview.tmp")

    project = Project.create(
        fp_tmp_simulation,
        project_id=Path(args.state_file).stem,
        project_mode="simulate",
        project_name=Path(args.state_file).stem,
        project_description="Simulation created via ASReview via "
        "command line interface",
    )

    # Get a name for the dataset
    if re.match(r"^([a-zA-Z0-9_-]+)\:([a-zA-Z0-9_-]+)$", args.dataset):
        ds = DatasetManager().find(args.dataset)
        filename = ds.filename
    else:
        filename = Path(args.dataset).name

    as_data = load_dataset(args.dataset)
    as_data.to_file(Path(fp_tmp_simulation, "data", filename))

    # Update the project.json.
    project.update_config(dataset_path=filename)

    # create a new settings object from arguments
    settings = ReviewSettings(
        classifier=args.model,
        n_instances=args.n_instances,
        stop_if=args.stop_if,
        n_prior_included=args.n_prior_included,
        n_prior_excluded=args.n_prior_excluded,
        query_strategy=args.query_strategy,
        balance_strategy=args.balance_strategy,
        feature_extraction=args.feature_extraction,
    )

    if args.config_file:
        settings.from_file(args.config_file)

    # Initialize models.
    random_state = get_random_state(args.seed)
    classifier_model = get_classifier(
        settings.classifier,
        random_state=random_state,
        **_unpack_params(settings.classifier_param),
    )
    query_model = get_query_model(
        settings.query_strategy,
        random_state=random_state,
        **_unpack_params(settings.query_param),
    )
    balance_model = get_balance_model(
        settings.balance_strategy,
        random_state=random_state,
        **_unpack_params(settings.balance_param),
    )
    feature_model = get_feature_model(
        settings.feature_extraction,
        random_state=random_state,
        **_unpack_params(settings.feature_param),
    )

    # prior knowledge
    if (
        args.prior_idx is not None
        and args.prior_record_id is not None
        and len(args.prior_idx) > 0
        and len(args.prior_record_id) > 0
    ):
        raise ValueError("Not possible to provide both prior_idx and prior_record_id")

    prior_idx = args.prior_idx
    if args.prior_record_id is not None and len(args.prior_record_id) > 0:
        prior_idx = _convert_id_to_idx(as_data, args.prior_record_id)

    if classifier_model.name.startswith("lstm-"):
        classifier_model.embedding_matrix = feature_model.get_embedding_matrix(
            as_data.texts, args.embedding_fp
        )

    # Initialize the review class.
    reviewer = Simulate(
        as_data,
        project=project,
        classifier=classifier_model,
        query_model=query_model,
        balance_model=balance_model,
        feature_model=feature_model,
        n_papers=args.n_papers,
        n_instances=args.n_instances,
        stop_if=args.stop_if,
        prior_indices=prior_idx,
        n_prior_included=args.n_prior_included,
        n_prior_excluded=args.n_prior_excluded,
        init_seed=args.init_seed,
        write_interval=args.write_interval,
    )

    review_id = uuid4().hex
    logging.debug(f"Create new review (state) with id {review_id}.")
    SQLiteState()._create_new_state_file(project.project_path, review_id)
    project.add_review(review_id)

    try:
        # Start the review process.
        project.update_review(status="review")

        with open_state(project) as s:
            prior_df = s.get_priors()

            print("The following records are prior knowledge:\n")
            for _, row in prior_df.iterrows():
                _print_record(as_data.record(row["record_id"]))

        print("Simulation started\n")
        reviewer.review()
    except Exception as err:
        # save the error to the project
        project.set_error(err)

        raise err

    print("\nSimulation finished")
    project.mark_review_finished()

    # create .ASReview file out of simulation folder
    project.export(args.state_file)
    shutil.rmtree(fp_tmp_simulation)


DESCRIPTION_SIMULATE = """
ASReview for simulation.

The simulation modus is used to measure the performance of the ASReview
software on existing systematic reviews. The software shows how many
papers you could have potentially skipped during the systematic
review."""


def _simulate_parser(prog="simulate", description=DESCRIPTION_SIMULATE):
    # parse arguments if available
    parser = argparse.ArgumentParser(
        prog=prog,
        description=description,
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Active learning parameters
    # File path to the data.
    parser.add_argument(
        "dataset",
        type=str,
        help="File path to the dataset or one of the benchmark datasets.",
    )
    # Initial data (prior knowledge)
    parser.add_argument(
        "--n_prior_included",
        default=DEFAULT_N_PRIOR_INCLUDED,
        type=int,
        help="Sample n prior included papers. "
        "Only used when --prior_idx is not given. "
        f"Default {DEFAULT_N_PRIOR_INCLUDED}",
    )

    parser.add_argument(
        "--n_prior_excluded",
        default=DEFAULT_N_PRIOR_EXCLUDED,
        type=int,
        help="Sample n prior excluded papers. "
        "Only used when --prior_idx is not given. "
        f"Default {DEFAULT_N_PRIOR_EXCLUDED}",
    )

    parser.add_argument(
        "--prior_idx",
        default=[],
        nargs="*",
        type=int,
        help="Prior indices by rownumber (0 is first rownumber).",
    )
    parser.add_argument(
        "--prior_record_id",
        default=[],
        nargs="*",
        type=int,
        help="Prior indices by record_id.",
    )
    # logging and verbosity
    parser.add_argument(
        "--state_file",
        "-s",
        default=None,
        type=str,
        help="Location to ASReview project file of simulation.",
    )
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        default=DEFAULT_CLASSIFIER,
        help=f"The prediction model for Active Learning. "
        f"Default: '{DEFAULT_CLASSIFIER}'.",
    )
    parser.add_argument(
        "-q",
        "--query_strategy",
        type=str,
        default=DEFAULT_QUERY_STRATEGY,
        help=f"The query strategy for Active Learning. "
        f"Default: '{DEFAULT_QUERY_STRATEGY}'.",
    )
    parser.add_argument(
        "-b",
        "--balance_strategy",
        type=str,
        default=DEFAULT_BALANCE_STRATEGY,
        help="Data rebalancing strategy mainly for RNN methods. Helps against"
        " imbalanced dataset with few inclusions and many exclusions. "
        f"Default: '{DEFAULT_BALANCE_STRATEGY}'",
    )
    parser.add_argument(
        "-e",
        "--feature_extraction",
        type=str,
        default=DEFAULT_FEATURE_EXTRACTION,
        help="Feature extraction method. Some combinations of feature"
        " extraction method and prediction model are impossible/ill"
        " advised."
        f"Default: '{DEFAULT_FEATURE_EXTRACTION}'",
    )
    parser.add_argument(
        "--init_seed",
        default=None,
        type=int,
        help="Seed for setting the prior indices if the --prior_idx option is "
        "not used. If the option --prior_idx is used with one or more "
        "index, this option is ignored.",
    )
    parser.add_argument(
        "--seed",
        default=None,
        type=int,
        help="Seed for the model (classifiers, balance strategies, "
        "feature extraction techniques, and query strategies).",
    )
    parser.add_argument(
        "--config_file",
        type=str,
        default=None,
        help="Configuration file with model settings" "and parameter values.",
    )
    parser.add_argument(
        "--n_instances",
        default=DEFAULT_N_INSTANCES,
        type=int,
        help="Number of papers queried each query." f"Default {DEFAULT_N_INSTANCES}.",
    )
    parser.add_argument(
        "--n_queries",
        type=type_n_queries,
        default="min",
        help="Deprecated, use 'stop_if' instead.",
    )
    parser.add_argument(
        "--stop_if",
        type=type_n_queries,
        default="min",
        help="The number of label actions to simulate. Default, 'min' "
        "will stop simulating when all relevant records are found. Use -1 "
        "to simulate all labels actions.",
    )
    parser.add_argument(
        "-n",
        "--n_papers",
        type=int,
        default=None,
        help="Deprecated, use 'stop_if' instead.",
    )
    parser.add_argument("--verbose", "-v", default=0, type=int, help="Verbosity")
    parser.add_argument(
        "--write_interval",
        "-w",
        default=None,
        type=int,
        help="The simulation data will be written after each set of this"
        "many labeled records. By default only writes data at the end"
        "of the simulation to make it as fast as possible.",
    )
    parser.add_argument(
        "--embedding",
        type=str,
        default=None,
        dest="embedding_fp",
        help="File path of embedding matrix. Required for LSTM models.",
    )
    return parser
