from yarp.store import FakeStoreConfig, FileStoreConfig


def check_store_cfg(store_cfg):
    store = store_cfg.build()

    assert store.load("initial") == "initial"

    store.store("value")

    assert store.load("initial") == "value"

    # building again works
    store = store_cfg.build()
    assert store.load("initial") == "value"

    # substores also work and don't interfere
    substore = (store_cfg / "sub").build()
    assert substore.load("initial") == "initial"

    substore.store("subvalue")

    assert substore.load("initial") == "subvalue"
    assert store.load("initial") == "value"


def test_fake_store():
    cfg = FakeStoreConfig()
    check_store_cfg(cfg)


def test_file_store(tmpdir):
    cfg = FileStoreConfig(tmpdir)
    check_store_cfg(cfg)


def test_build_value():
    cfg = FakeStoreConfig()

    v = cfg.build_value(1)
    assert v.value == 1

    # iniaial value not saved
    v = cfg.build_value(2)
    assert v.value == 2

    v.value = 3

    # value loaded
    v = cfg.build_value(1)
    assert v.value == 3


def test_file_store_error(tmpdir):
    cfg = FileStoreConfig(tmpdir)
    store = cfg.build()

    store.store("value")  # makes sure we wrote to the right path

    with open(store.path, "w") as f:
        f.write("not a pickle")

    assert store.load("default") == "default"
