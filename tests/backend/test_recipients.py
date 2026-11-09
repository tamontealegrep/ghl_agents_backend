import pytest

from agent_backend.recipients import split_recipients


@pytest.mark.parametrize("raw", [None, "", "   ", " , ; "])
def test_empty_value_means_no_recipients(raw):
    assert split_recipients(raw) == ([], [])


def test_one_address():
    assert split_recipients("team@example.org") == (["team@example.org"], [])


def test_several_addresses_with_mixed_separators_and_spaces():
    raw = "a@x.org, b@x.org;c@x.org  d@x.org"
    assert split_recipients(raw)[0] == ["a@x.org", "b@x.org", "c@x.org", "d@x.org"]


def test_duplicates_are_dropped_ignoring_case():
    assert split_recipients("A@x.org, a@X.org")[0] == ["A@x.org"]


def test_malformed_entries_are_reported_and_valid_ones_kept():
    valid, invalid = split_recipients("ok@x.org, not-an-address, @x.org, also@bad")
    assert valid == ["ok@x.org"]
    assert invalid == ["not-an-address", "@x.org", "also@bad"]
