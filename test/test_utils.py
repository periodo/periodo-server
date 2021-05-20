from periodo import utils


def test_isoformat():
    assert utils.isoformat(1621369128) == '2021-05-18T20:18:48+00:00'


def test_isoparse():
    assert utils.isoparse('2021-05-18T20:18:48+00:00') == 1621369128
