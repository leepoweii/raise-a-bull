from raisebull.discord_bot import extract_domain_from_channel, _split_message

def test_extract_domain_unknown_channel():
    assert extract_domain_from_channel("some-random-channel") == "general"

def test_extract_domain_known_mapping():
    assert extract_domain_from_channel("morning") == "daily"

def test_project_channel_no_longer_special():
    # Samantha's _PROJECT_CHANNELS are gone — unknown channels → "general"
    assert extract_domain_from_channel("夢酒館") == "general"

def test_split_message_short():
    chunks = _split_message("hello")
    assert chunks == ["hello"]

def test_split_message_long():
    text = "x" * 4000
    chunks = _split_message(text)
    assert all(len(c) <= 1900 for c in chunks)
    assert "".join(chunks) == text
