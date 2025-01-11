from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath, Path
import pickle
import traceback
from .value import Value, NoValue


@dataclass
class Store:
    """base class for objects used to store and load one particular piece of
    data"""

    def load(self, default):
        raise NotImplementedError()

    def store(self, value):
        raise NotImplementedError()

    def close(self):
        pass

    def store_atexit(self, get_value):
        import atexit

        @atexit.register
        def run():
            self.store(get_value())


@dataclass
class StoreConfig:
    """base class for 'configuration' objects that can make a Store

    The piece of data to store or load is represented by a path, which must be
    unique.

    Use `config / "something"` to make a new configuration which stores data in
    a sub-directory. Using this, each place that needs to store data in a
    hierarchy of components can be given a unique and consistent path
    """

    path: PurePosixPath = PurePosixPath()

    def __truediv__(self, other):
        return replace(self, path=self.path / other)

    def build(self) -> Store:
        raise NotImplementedError()

    def build_value(
        self, initial_value=NoValue, inputs=(), store_initial=False
    ) -> Value:
        """build a persistent value backed by this store.

        initial_value is the value used if no value was previously stored.

        If store_initial, the initial value will be stored. This might be
        useful if initial_value is not constalt.

        Other parameters are the same as for Value.
        """

        store = self.build()

        v = Value(initial_value=store.load(initial_value), inputs=inputs)

        v.on_value_changed(store.store)
        if store_initial:
            store.store(v.value)

        return v


# file-backed implementation


@dataclass
class FileStore(Store):
    """store data in a pickle file with the given path"""

    path: Path

    def store(self, value):
        with open(self.path, "wb") as f:
            pickle.dump(value, f)

    def load(self, default):
        try:
            with open(self.path, "rb") as f:
                return pickle.load(f)
        except FileNotFoundError:
            return default
        except Exception:
            traceback.print_exc()
            return default


@dataclass
class FileStoreConfig(StoreConfig):
    """configuration for making FileStores in a given base directory"""

    base_dir: Path | str = Path()

    def build(self):
        full_path = Path(self.base_dir) / self.path / "state.pickle"

        full_path.parent.mkdir(parents=True, exist_ok=True)

        return FileStore(full_path)


# null implementation


class NullStore(Store):
    def store(self, value):
        pass

    def load(self, default):
        return default


class NullStoreConfig(StoreConfig):
    """config for a Store which does not save data"""

    def build(self):
        return NullStore()


null_store = NullStoreConfig()


# fake store for use in testing

# unlike NullStore this actually stores data, but only in memory. atexit stores
# are ran manually, as in testing we need to see the effects of these before
# the program exits


@dataclass
class FakeStoreData:
    store: dict = field(default_factory=dict)
    atexit_cbs: list = field(default_factory=list)

    def run_atexits(self):
        for cb in self.atexit_cbs:
            cb()
        self.atexit_cbs.clear()


@dataclass
class FakeStore(Store):
    data: FakeStoreData
    path: PurePosixPath

    def load(self, default):
        return self.data.store.get(self.path, default)

    def store(self, value):
        self.data.store[self.path] = value

    def store_atexit(self, get_value):
        def cb():
            self.store(get_value())

        self.data.atexit_cbs.append(cb)


@dataclass
class FakeStoreConfig(StoreConfig):
    data: FakeStoreData = field(default_factory=FakeStoreData)

    def build(self):
        return FakeStore(self.data, self.path)


# default for use in scripts; default values should be null_store


def _get_default_store():
    from os import environ

    env_path = environ.get("YARP_STORE_PATH")
    if env_path is not None:
        return FileStoreConfig(base_dir=Path(env_path))

    return FileStoreConfig()


default_store = _get_default_store()
