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

__all__ = [
    "LogisticClassifier",
    "NaiveBayesClassifier",
    "RandomForestClassifier",
    "SVMClassifier",
    "get_classifier",
    "get_classifier_class",
    "list_classifiers",
]

from asreview.models.classifiers.logistic import LogisticClassifier
from asreview.models.classifiers.nb import NaiveBayesClassifier
from asreview.models.classifiers.rf import RandomForestClassifier
from asreview.models.classifiers.svm import SVMClassifier
from asreview.models.classifiers.utils import get_classifier
from asreview.models.classifiers.utils import get_classifier_class
from asreview.models.classifiers.utils import list_classifiers

"""Machine learning classifiers to classify the documents.

There are several machine learning classifiers available. In configuration
files, parameters are found under the section ``[classifier_param]``.
"""
