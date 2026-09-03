from pulsar.dashboard.widgets.process_widget import format_mem


def test_format_bytes():
    assert format_mem(500) == "500"


def test_format_kilobytes():
    assert format_mem(1536) == "1.5k"


def test_format_megabytes():
    assert format_mem(1_572_864) == "1.5M"
