from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath, Path
import pickle
import traceback
from .value import Value, NoValue


@dataclass
class Store:
    """base class for objects used to store and load one particular piece of
    data"""

    version: int = field(default=0, kw_only=True)

    def load(self, default, validate=None, convert=None):
        """load the value, or return default

        if the stored version does not match the current version (specified in
        StoreConfig.build), the new value will be convert(old_version,
        old_value), or default

        validate will be called with the value, and may raise an exception for
        invalid values (causing the default to be returned)
        """
        # the only thing that should raise is validation, but any exception in
        # here is Very Bad because it can not be cleared by a restart, so
        # handle any exception by returning the default
        try:
            stored_version, value = self._load_impl((self.version, default))

            if stored_version != self.version:
                if convert is not None:
                    value = convert(stored_version, value)
                else:
                    value = default

            if validate is not None:
                validate(value)

            return value

        except Exception:
            traceback.print_exc()
            return default

    def store(self, value):
        """store the value"""
        self._store_impl((self.version, value))

    def close(self):
        pass

    def store_atexit(self, get_value):
        import atexit

        @atexit.register
        def run():
            self.store(get_value())

    # implement in sub-classes

    def _load_impl(self, default):
        raise NotImplementedError()

    def _store_impl(self, value):
        raise NotImplementedError()


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

    def build(self, **kwargs) -> Store:
        """make a Store. kwargs will be passed to Store"""
        raise NotImplementedError()

    def build_value(
        self,
        initial_value=NoValue,
        inputs=(),
        store_initial=False,
        validate=None,
        convert=None,
        **kwargs
    ) -> Value:
        """build a persistent value backed by this store.

        initial_value is the value used if no value was previously stored.

        If store_initial, the initial value will be stored. This might be
        useful if initial_value is not constant.

        Other parameters are the same as for Value, and kwargs are passed to
        self.build.
        """

        store = self.build(**kwargs)

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

    def _store_impl(self, value):
        with open(self.path, "wb") as f:
            pickle.dump(value, f)

    def _load_impl(self, default):
        try:
            with open(self.path, "rb") as f:
                return pickle.load(f)
        except FileNotFoundError:
            return default


@dataclass
class FileStoreConfig(StoreConfig):
    """configuration for making FileStores in a given base directory"""

    base_dir: Path | str = Path()

    def build(self, **kwargs):
        full_path = Path(self.base_dir) / self.path / "state.pickle"

        full_path.parent.mkdir(parents=True, exist_ok=True)

        return FileStore(full_path, **kwargs)


# null implementation


class NullStore(Store):
    def _store_impl(self, value):
        pass

    def _load_impl(self, default):
        return default


class NullStoreConfig(StoreConfig):
    """config for a Store which does not save data"""

    def build(self, **kwargs):
        return NullStore(**kwargs)


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

    def _load_impl(self, default):
        return self.data.store.get(self.path, default)

    def _store_impl(self, value):
        self.data.store[self.path] = value

    def store_atexit(self, get_value):
        def cb():
            self.store(get_value())

        self.data.atexit_cbs.append(cb)


@dataclass
class FakeStoreConfig(StoreConfig):
    data: FakeStoreData = field(default_factory=FakeStoreData)

    def build(self, **kwargs):
        return FakeStore(self.data, self.path, **kwargs)


# default for use in scripts; default values should be null_store


def _get_default_store():
    from os import environ

    env_path = environ.get("YARP_STORE_PATH")
    if env_path is not None:
        return FileStoreConfig(base_dir=Path(env_path))

    return FileStoreConfig()


default_store = _get_default_store()
