import pytest

from agent_backend.recipients import split_recipients


@pytest.mark.parametrize("raw", [None, "", "   ", " , ; "])
def test_empty_value_means_no_recipients(raw):
    """An empty value gives no recipients."""
    assert split_recipients(raw) == ([], [])


def test_one_address():
    """A single address is returned as is."""
    assert split_recipients("team@example.org") == (["team@example.org"], [])


def test_mixed_separators():
    """Addresses split on commas, semicolons and spaces."""
    raw = "a@x.org, b@x.org;c@x.org  d@x.org"
    assert split_recipients(raw)[0] == ["a@x.org", "b@x.org", "c@x.org", "d@x.org"]


def test_duplicates_are_dropped_ignoring_case():
    """Duplicate addresses are dropped, ignoring case."""
    assert split_recipients("A@x.org, a@X.org")[0] == ["A@x.org"]


def test_malformed_reported_valid_kept():
    """Malformed entries are reported and valid ones kept."""
    valid, invalid = split_recipients("ok@x.org, not-an-address, @x.org, also@bad")
    assert valid == ["ok@x.org"]
    assert invalid == ["not-an-address", "@x.org", "also@bad"]
