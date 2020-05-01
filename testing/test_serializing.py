import toolz
import immutables
import bugdex.serializing
import json


def test_sanity_1():
    # make sure that JSONEncoder() defaults to same attributes as json._default_encoder.
    assert json.encoder.JSONEncoder().__dict__ == json._default_encoder.__dict__


def test_custom_encoder_default():
    # bugdex.serializing.replace_json_default_encoder(bugdex.serializing.CustomEncoder)

    encoder = bugdex.serializing.CustomEncoder()

    assert encoder.deep_represent(immutables.Map(a=1)) == dict(a=1)
    assert encoder.deep_represent({immutables.Map(a=1)}) == [dict(a=1)]


def test_custom_encoder():
    # bugdex.serializing.replace_json_default_encoder(bugdex.serializing.CustomEncoder)

    # sanity check
    assert json.loads(json.dumps(dict(a=1), cls=bugdex.serializing.CustomEncoder)) == dict(a=1)

    assert json.loads(json.dumps(immutables.Map(a=1), cls=bugdex.serializing.CustomEncoder)) == dict(a=1)
