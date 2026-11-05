def test_events_are_remembered(store):
    assert not store.seen("evt_1")
    store.mark("evt_1", "invoice.paid", "ok")
    assert store.seen("evt_1")


def test_staleness_is_per_object_and_keeps_the_newest(store):
    assert not store.is_stale("sub:1", 100)
    store.touch("sub:1", 200)
    store.touch("sub:1", 150)          # an older touch must not move the clock back
    assert store.is_stale("sub:1", 199)
    assert not store.is_stale("sub:1", 200)
    assert not store.is_stale("sub:2", 1)


def test_links(store):
    assert store.get_link("sub_1") is None
    store.set_link("sub_1", "d1")
    assert store.get_link("sub_1") == "d1"


def test_lock_is_shared_per_key(store):
    assert store.lock_for("a") is store.lock_for("a")
    assert store.lock_for("a") is not store.lock_for("b")
