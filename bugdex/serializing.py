from __future__ import annotations
import json
import datetime
import operator
from warnings import warn
from numbers import Number
from typing import Mapping, Iterable

import toolz

_original_default_encoder = None

contains = toolz.curry(operator.contains)


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)


class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Mapping):
            return dict(obj)
        elif isinstance(obj, Iterable):
            return list(obj)
        else:
            return super().default(obj)

    def deep_represent(self, obj):
        if isinstance(obj, (str, Number)):
            return obj

        default_obj = self.default(obj)
        if isinstance(default_obj, dict):
            return {self.deep_represent(k): self.deep_represent(v) for k, v in default_obj.items()}
        elif isinstance(default_obj, list):
            return [self.deep_represent(elt) for elt in default_obj]
        else:
            raise NotImplementedError(f'invalid type {type(default_obj)}')


def replace_json_default_encoder(encoder, /):
    """
    :param encoder:
    :return:
    """
    warn(DeprecationWarning("use `CustomEncoder.deep_represent` instead; see `test_serializing` for examples"))

    global _original_default_encoder

    print('replacing json default encoder')

    if not _original_default_encoder:
        _original_default_encoder = json._default_encoder

    json._default_encoder = encoder()
