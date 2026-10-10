from mapforge.validate.checks import WARNING, check_timings

CFG = {"min_t_s": 14, "max_t_s": 26, "min_ct_lead_s": 3}


def row(site, t, ct):
    return {
        "site": site,
        "T": {"median_s": t},
        "CT": {"median_s": ct},
        "ct_lead_s": round(t - ct, 1),
    }


def rules(rows):
    return sorted(f.rule for f in check_timings(rows, CFG, WARNING))


def test_dust2_like_timings_are_fine():
    assert rules([row("A", 18.2, 4.5), row("B", 17.4, 8.5)]) == []


def test_compact_slow_and_late_ct_are_flagged():
    assert rules([row("A", 12.6, 3.9)]) == ["timing_t_fast"]
    assert rules([row("B", 30.0, 10.0)]) == ["timing_t_slow"]
    assert rules([row("A", 16.0, 14.0)]) == ["timing_ct_late"]
