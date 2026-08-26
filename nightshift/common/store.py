"""Document store abstraction.

Two backends, one contract:

* ``MemoryStore`` — deterministic, no network. Used by the offline drill corpus, the
  100-run campaign, and every unit test.
* ``FirestoreStore`` — the live operational plane.

The only operation that genuinely needs a transaction is committing a rescue effect, so
that is the operation the interface is shaped around: ``run_transaction`` gets a
consistent read set and an all-or-nothing write set. Everything else is a plain get or
query.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


class ConcurrentModificationError(RuntimeError):
    """A transaction's read set changed underneath it. The caller should retry."""


@dataclass
class Write:
    collection: str
    doc_id: str
    data: dict[str, Any]
    merge: bool = False


@dataclass
class TxnContext:
    """Handed to a transaction body. Reads are recorded; writes are buffered."""

    _store: Store
    _reads: dict[tuple[str, str], int] = field(default_factory=dict)
    _writes: list[Write] = field(default_factory=list)

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        doc, version = self._store._read_versioned(collection, doc_id)
        self._reads[(collection, doc_id)] = version
        return doc

    def query(self, collection: str, **equals: Any) -> list[dict[str, Any]]:
        results = self._store._query_versioned(collection, **equals)
        for doc_id, _doc, version in results:
            self._reads[(collection, doc_id)] = version
        return [doc for _id, doc, _v in results]

    def set(
        self, collection: str, doc_id: str, data: dict[str, Any], *, merge: bool = False
    ) -> None:
        self._writes.append(Write(collection, doc_id, data, merge))

    @property
    def writes(self) -> list[Write]:
        return self._writes

    @property
    def reads(self) -> dict[tuple[str, str], int]:
        return self._reads


class Store(ABC):
    """Minimal document store."""

    backend: str

    @abstractmethod
    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def set(
        self, collection: str, doc_id: str, data: dict[str, Any], *, merge: bool = False
    ) -> None: ...

    @abstractmethod
    def query(self, collection: str, **equals: Any) -> list[dict[str, Any]]: ...

    @abstractmethod
    def delete(self, collection: str, doc_id: str) -> None: ...

    @abstractmethod
    def run_transaction(self, body: Callable[[TxnContext], T], *, max_attempts: int = 5) -> T: ...

    @abstractmethod
    def _read_versioned(
        self, collection: str, doc_id: str
    ) -> tuple[dict[str, Any] | None, int]: ...

    @abstractmethod
    def _query_versioned(
        self, collection: str, **equals: Any
    ) -> list[tuple[str, dict[str, Any], int]]: ...

    def collections(self) -> Iterable[str]:  # pragma: no cover - diagnostics only
        return []


class MemoryStore(Store):
    """In-process store with optimistic concurrency.

    The version counters are not decoration: the concurrency drill (D4) runs two
    reservation attempts against the same destination from two threads, and this is
    what makes the loser actually lose instead of silently overwriting.
    """

    backend = "memory"

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._versions: dict[str, dict[str, int]] = {}
        self._lock = threading.RLock()
        self._clock = 0

    # -- plain operations ---------------------------------------------------------

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        with self._lock:
            doc = self._data.get(collection, {}).get(doc_id)
            return dict(doc) if doc is not None else None

    def set(
        self, collection: str, doc_id: str, data: dict[str, Any], *, merge: bool = False
    ) -> None:
        with self._lock:
            self._apply(Write(collection, doc_id, data, merge))

    def delete(self, collection: str, doc_id: str) -> None:
        with self._lock:
            self._data.get(collection, {}).pop(doc_id, None)
            self._bump(collection, doc_id)

    def query(self, collection: str, **equals: Any) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(d) for _i, d, _v in self._query_versioned(collection, **equals)]

    # -- internals ----------------------------------------------------------------

    def _bump(self, collection: str, doc_id: str) -> int:
        self._clock += 1
        self._versions.setdefault(collection, {})[doc_id] = self._clock
        return self._clock

    def _apply(self, w: Write) -> None:
        bucket = self._data.setdefault(w.collection, {})
        if w.merge and w.doc_id in bucket:
            bucket[w.doc_id] = {**bucket[w.doc_id], **w.data}
        else:
            bucket[w.doc_id] = dict(w.data)
        self._bump(w.collection, w.doc_id)

    def _read_versioned(self, collection: str, doc_id: str) -> tuple[dict[str, Any] | None, int]:
        with self._lock:
            doc = self._data.get(collection, {}).get(doc_id)
            version = self._versions.get(collection, {}).get(doc_id, 0)
            return (dict(doc) if doc is not None else None), version

    def _query_versioned(
        self, collection: str, **equals: Any
    ) -> list[tuple[str, dict[str, Any], int]]:
        with self._lock:
            bucket = self._data.get(collection, {})
            versions = self._versions.get(collection, {})
            out = []
            for doc_id, doc in bucket.items():
                if all(doc.get(k) == v for k, v in equals.items()):
                    out.append((doc_id, dict(doc), versions.get(doc_id, 0)))
            return sorted(out, key=lambda r: r[0])

    def run_transaction(self, body: Callable[[TxnContext], T], *, max_attempts: int = 5) -> T:
        last: Exception | None = None
        for _attempt in range(max_attempts):
            ctx = TxnContext(_store=self)
            result = body(ctx)
            with self._lock:
                stale = [
                    key
                    for key, seen in ctx.reads.items()
                    if self._versions.get(key[0], {}).get(key[1], 0) != seen
                ]
                if stale:
                    last = ConcurrentModificationError(f"read set changed: {stale}")
                    continue
                for w in ctx.writes:
                    self._apply(w)
                return result
        raise last or ConcurrentModificationError("transaction could not commit")

    def collections(self) -> Iterable[str]:
        return sorted(self._data)

    def export(self) -> dict[str, dict[str, dict[str, Any]]]:
        with self._lock:
            return {c: {k: dict(v) for k, v in docs.items()} for c, docs in self._data.items()}

    def load(self, data: dict[str, dict[str, dict[str, Any]]]) -> None:
        with self._lock:
            for collection, docs in data.items():
                for doc_id, doc in docs.items():
                    self._apply(Write(collection, doc_id, doc))


class FirestoreStore(Store):
    """Firestore Native backend.

    Firestore transactions give us the serializable read-modify-write we need for N1:
    the capacity check and the reservation write land in one atomic unit, so two
    concurrent incidents cannot both observe the same free slots and both take them.
    """

    backend = "firestore"

    def __init__(self, project: str, database: str = "(default)", prefix: str = "") -> None:
        from google.cloud import firestore

        self._client = firestore.Client(project=project, database=database)
        self._prefix = prefix
        self._firestore = firestore

    def _col(self, collection: str) -> str:
        return f"{self._prefix}{collection}" if self._prefix else collection

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        snap = self._client.collection(self._col(collection)).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def set(
        self, collection: str, doc_id: str, data: dict[str, Any], *, merge: bool = False
    ) -> None:
        self._client.collection(self._col(collection)).document(doc_id).set(data, merge=merge)

    def delete(self, collection: str, doc_id: str) -> None:
        self._client.collection(self._col(collection)).document(doc_id).delete()

    def query(self, collection: str, **equals: Any) -> list[dict[str, Any]]:
        ref: Any = self._client.collection(self._col(collection))
        for key, value in equals.items():
            ref = ref.where(filter=self._firestore.FieldFilter(key, "==", value))
        return [d.to_dict() for d in ref.stream()]

    def _read_versioned(self, collection: str, doc_id: str) -> tuple[dict[str, Any] | None, int]:
        # Firestore's own transaction machinery tracks the read set; the version is unused.
        return self.get(collection, doc_id), 0

    def _query_versioned(
        self, collection: str, **equals: Any
    ) -> list[tuple[str, dict[str, Any], int]]:
        ref: Any = self._client.collection(self._col(collection))
        for key, value in equals.items():
            ref = ref.where(filter=self._firestore.FieldFilter(key, "==", value))
        return [(d.id, d.to_dict(), 0) for d in ref.stream()]

    def run_transaction(self, body: Callable[[TxnContext], T], *, max_attempts: int = 5) -> T:
        client = self._client
        store = self

        @self._firestore.transactional  # type: ignore[misc]
        def _run(transaction: Any) -> T:
            ctx = _FirestoreTxnContext(store, transaction, client)
            result = body(ctx)  # type: ignore[arg-type]
            for w in ctx.writes:
                ref = client.collection(store._col(w.collection)).document(w.doc_id)
                transaction.set(ref, w.data, merge=w.merge)
            return result

        return _run(client.transaction(max_attempts=max_attempts))  # type: ignore[no-any-return]


class _FirestoreTxnContext(TxnContext):
    """Reads go through the Firestore transaction so the read set is tracked server-side."""

    def __init__(self, store: FirestoreStore, transaction: Any, client: Any) -> None:
        super().__init__(_store=store)  # type: ignore[arg-type]
        self._transaction = transaction
        self._client = client
        self._fstore = store

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        ref = self._client.collection(self._fstore._col(collection)).document(doc_id)
        snaps = list(ref.get(transaction=self._transaction) for _ in (0,))
        snap = snaps[0]
        return snap.to_dict() if snap.exists else None

    def query(self, collection: str, **equals: Any) -> list[dict[str, Any]]:
        import google.cloud.firestore as firestore

        ref: Any = self._client.collection(self._fstore._col(collection))
        for key, value in equals.items():
            ref = ref.where(filter=firestore.FieldFilter(key, "==", value))
        return [d.to_dict() for d in ref.stream(transaction=self._transaction)]


def build_store(
    backend: str, *, project: str = "", database: str = "(default)", prefix: str = ""
) -> Store:
    if backend == "firestore":
        if not project:
            raise ValueError("firestore backend requires GOOGLE_CLOUD_PROJECT")
        return FirestoreStore(project=project, database=database, prefix=prefix)
    return MemoryStore()
