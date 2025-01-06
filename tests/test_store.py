from yarp.store import Store, StoreConfig, FileStore, FileStoreConfig
from dataclasses import dataclass, field
from pathlib import PosixPath


@dataclass
class DictStoreData:
    store: dict = field(default_factory=dict)
    atexit_cbs: list = field(default_factory=list)

    def run_atexits(self):
        for cb in self.atexit_cbs:
            cb()
        self.atexit_cbs.clear()


@dataclass
class DictStore(Store):
    data: DictStoreData
    path: PosixPath

    def load(self, default):
        return self.data.store.get(self.path, default)

    def store(self, value):
        self.data.store[self.path] = value

    def store_atexit(self, get_value):
        def cb():
            self.store(get_value())

        self.data.atexit_cbs.append(cb)


@dataclass
class DictStoreConfig(StoreConfig):
    data: DictStoreData = field(default_factory=DictStoreData)

    def build(self):
        return DictStore(self.data, self.path)


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


def test_dict_store():
    cfg = DictStoreConfig()
    check_store_cfg(cfg)


def test_file_store(tmpdir):
    cfg = FileStoreConfig(tmpdir)
    check_store_cfg(cfg)

def test_dict_store():
    cfg = DictStoreConfig()

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
