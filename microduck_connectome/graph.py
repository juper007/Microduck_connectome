"""Read-only queries over a validated bounded connectivity artifact.

Views retain root provenance and full-source normalization; they are not new
extraction artifacts. Public record results are detached mutable copies.
"""

from copy import deepcopy
import json

from .annotations import MAX_BODY_ID
from .graph_cache import graph_cache_key, load_graph


class ConnectomeGraph:
    """Deterministic directed graph with body IDs as canonical identities.

    Invalid IDs raise ValueError; IDs absent from this graph/view raise KeyError.
    A missing edge between present nodes returns None. Queries cover only the
    edges retained in the current artifact/view, not all MaleCNS connections.
    """

    __slots__ = ("_root_key", "_root_manifest", "_annotation_provenance",
                 "_nodes", "_edges", "_sums", "_incoming", "_outgoing")

    def __init__(self, artifact):
        snapshot = deepcopy(artifact)
        self._root_key = graph_cache_key(snapshot)
        # Use the same JSON representation validated by the cache boundary.
        snapshot = json.loads(json.dumps(snapshot))
        self._root_manifest = snapshot["manifest"]
        self._annotation_provenance = {
            key: value for key, value in snapshot["annotations"].items()
            if key != "records"
        }
        self._nodes = {row["body_id"]: row for row in snapshot["annotations"]["records"]}
        self._sums = {row["body_id"]: row["raw_weight_sum"]
                      for row in snapshot["full_outgoing_sums"]}
        self._index_edges(snapshot["edges"])

    @classmethod
    def from_cache(cls, cache_dir, expected_key):
        """Load via the cache's expected-key and schema/integrity checks."""
        return cls(load_graph(cache_dir, expected_key))

    def _index_edges(self, edges):
        self._edges = {}
        self._incoming = {body_id: [] for body_id in self._nodes}
        self._outgoing = {body_id: [] for body_id in self._nodes}
        for row in edges:
            source, target = row["source_body_id"], row["target_body_id"]
            self._edges[source, target] = row
            self._incoming[target].append(row)
            self._outgoing[source].append(row)

    def _require_node(self, body_id):
        if type(body_id) is not int or not 1 <= body_id <= MAX_BODY_ID:
            raise ValueError("body_id must be an integer in 1..2**63-1 (no coercion)")
        if body_id not in self._nodes:
            raise KeyError(body_id)

    @property
    def body_ids(self):
        """Current node IDs in ascending order, including isolated nodes."""
        return tuple(self._nodes)

    @property
    def root_key(self):
        """Content/cache identity of the original artifact, even in nested views."""
        return self._root_key

    @property
    def root_manifest(self):
        """Detached root manifest; its counts/hashes describe the root, not a view."""
        return deepcopy(self._root_manifest)

    @property
    def annotation_provenance(self):
        """Detached root annotation metadata (source note, dataset, version, commit)."""
        return deepcopy(self._annotation_provenance)

    def nodes(self):
        """Detached annotations ordered by body ID."""
        return tuple(deepcopy(row) for row in self._nodes.values())

    def node(self, body_id):
        self._require_node(body_id)
        return deepcopy(self._nodes[body_id])

    def edges(self):
        """Detached edges ordered by (source body ID, target body ID)."""
        return tuple(deepcopy(row) for row in self._edges.values())

    def edge(self, source_body_id, target_body_id):
        self._require_node(source_body_id)
        self._require_node(target_body_id)
        return deepcopy(self._edges.get((source_body_id, target_body_id)))

    def incoming(self, body_id):
        """Incoming edges ordered by source ID, with raw and normalized weights."""
        self._require_node(body_id)
        return tuple(deepcopy(row) for row in self._incoming[body_id])

    def outgoing(self, body_id):
        """Outgoing edges ordered by target ID, with raw and normalized weights."""
        self._require_node(body_id)
        return tuple(deepcopy(row) for row in self._outgoing[body_id])

    def full_outgoing_sum(self, body_id):
        """Exact root source denominator, including targets absent from this view."""
        self._require_node(body_id)
        return self._sums[body_id]

    def select_type(self, cell_type):
        """Exact source type match; None selects explicitly unknown types only.

        Matching is case-sensitive without trimming or biological inference.
        Unknown type names return an empty tuple; blank/invalid names are errors.
        """
        if cell_type is not None:
            if not isinstance(cell_type, str) or not cell_type.strip():
                raise ValueError("cell_type must be a nonblank string or None")
            try:
                cell_type.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("cell_type must be valid Unicode") from None
        return tuple(body_id for body_id, row in self._nodes.items()
                     if row["cell_type"] == cell_type)

    def induced(self, body_ids):
        """Select current nodes and connecting edges without renormalization.

        Accept an iterable of IDs, deduplicate, and order ascending. Unknown or
        previously excluded IDs are errors, so nested views cannot expand.
        """
        selected = set()
        for body_id in body_ids:
            self._require_node(body_id)
            selected.add(body_id)
        view = object.__new__(type(self))
        view._root_key = self._root_key
        view._root_manifest = self._root_manifest
        view._annotation_provenance = self._annotation_provenance
        view._nodes = {body_id: self._nodes[body_id] for body_id in sorted(selected)}
        view._sums = {body_id: self._sums[body_id] for body_id in view._nodes}
        view._index_edges(row for (source, target), row in self._edges.items()
                          if source in selected and target in selected)
        return view
