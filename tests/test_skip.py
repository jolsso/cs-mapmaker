"""The skip flag (maps/<map>/skip.json): the human asks the loop to skip the current iteration."""

from mapforge import skip


def test_request_pending_clear(tmp_path):
    (tmp_path / "de_x").mkdir()
    assert skip.pending(tmp_path, "de_x") is None
    req = skip.request(tmp_path, "de_x", "apply my change now")
    assert req["reason"] == "apply my change now" and req["time"]
    assert skip.pending(tmp_path, "de_x") == req
    skip.clear(tmp_path, "de_x")
    assert skip.pending(tmp_path, "de_x") is None
    skip.clear(tmp_path, "de_x")  # clearing twice is fine
