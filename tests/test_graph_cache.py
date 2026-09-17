"""Offline cache integrity tests; synthetic fixtures are not biological evidence."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from microduck_connectome.graph_cache import (
    GraphCacheError, graph_cache_key, load_graph, store_graph,
)
from test_connectivity import annotations, digest, edge, extract


class GraphCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_roundtrip_no_aliases_and_idempotence(self):
        graph = extract([edge(1, 2, 3), edge(1, 99, 7)])
        original = copy.deepcopy(graph)
        key = store_graph(self.root, graph)
        self.assertEqual(key, graph_cache_key(graph))
        self.assertEqual(load_graph(self.root, key), graph)
        self.assertEqual(store_graph(self.root, graph), key)
        loaded = load_graph(self.root, key)
        loaded['manifest']['selection_rules'] = 'changed'
        self.assertEqual(load_graph(self.root, key), original)
        self.assertEqual(graph, original)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_real_fixture(self):
        path = Path(__file__).resolve().parents[1] / 'docs/tasks/P1-03-real-graph.json'
        graph = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(load_graph(self.root, store_graph(self.root, graph)), graph)

    def test_identity_covers_provenance_and_timestamp(self):
        graph = extract()
        key = store_graph(self.root, graph)
        for field, value in (
            ('source_sha256', 'd' * 64), ('query_or_extraction_config', 'changed config'),
            ('confidence_filter', 'changed filter'), ('selection_rules', 'changed rules'),
            ('created_utc', '2026-09-18T00:00:00Z'), ('extraction_tool_version', 'e' * 40),
            ('seed_populations', ['changed']), ('readout_populations', ['changed']),
        ):
            changed = copy.deepcopy(graph)
            changed['manifest'][field] = value
            new_key = graph_cache_key(changed)
            self.assertNotEqual(key, new_key)
            with self.assertRaises(FileNotFoundError):
                load_graph(self.root, new_key)
        reordered = dict(reversed(list(graph.items())))
        self.assertEqual(key, graph_cache_key(reordered))

    def test_bad_keys_and_missing_entry(self):
        for key in ('../file', '/file', '..\\file', 'A' * 64, 'a' * 63, 'a' * 64 + '\n', None, 3):
            with self.subTest(key=key), self.assertRaises(GraphCacheError):
                load_graph(self.root, key)
        with self.assertRaises(FileNotFoundError):
            load_graph(self.root, 'f' * 64)

    def test_corruption_and_wrong_identity(self):
        graph = extract()
        key = store_graph(self.root, graph)
        path = self.root / (key + '.json')
        for data in (b'', b'{}', path.read_bytes() + b'\n'):
            path.write_bytes(data)
            with self.assertRaises(GraphCacheError):
                load_graph(self.root, key)
            with self.assertRaises(GraphCacheError):
                store_graph(self.root, graph)
            self.assertEqual(path.read_bytes(), data)

    def test_malformed_even_when_digest_matches(self):
        for data in (b'{', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}',
                     b'\xff', b'[]', b'null', b'{}', b'{"schema_version":"future"}'):
            key = hashlib.sha256(data).hexdigest()
            (self.root / (key + '.json')).write_bytes(data)
            with self.subTest(data=data), self.assertRaises(GraphCacheError):
                load_graph(self.root, key)

    def test_semantic_validation_after_rehashing(self):
        def bad_normalization(g):
            g['edges'][0]['normalized_weight'] = .75
            g['manifest']['edge_table_hash'] = digest(g['edges'])
        def bad_type(g):
            g['edges'][0]['source_type'] = 'wrong'
            g['manifest']['edge_table_hash'] = digest(g['edges'])
        def small_sum(g):
            g['full_outgoing_sums'][0]['raw_weight_sum'] = 2
            g['manifest']['full_outgoing_sums_hash'] = digest(g['full_outgoing_sums'])
        changes = [bad_normalization, bad_type, small_sum,
                   lambda g: g.update(schema_version='future'),
                   lambda g: g.update(extra=1),
                   lambda g: g['manifest'].update(node_count=True),
                   lambda g: g['manifest'].update(edge_count=2),
                   lambda g: g['manifest'].update(source_edge_count=0),
                   lambda g: g['manifest'].update(source_raw_weight_sum=1),
                   lambda g: g['manifest'].update(source_edge_table_hash='0' * 64),
                   lambda g: g['manifest'].update(dataset='other'),
                   lambda g: g['manifest'].update(created_utc='bad'),
                   lambda g: g['annotations']['records'].append(g['annotations']['records'][0]),
                   lambda g: g['edges'][0].update(normalized_weight=float('inf')),
                   lambda g: g['edges'][0].update(source_body_id=True),
                   lambda g: g['edges'].append(g['edges'][0])]
        for change in changes:
            graph = extract()
            change(graph)
            with self.subTest(change=change), self.assertRaises(GraphCacheError):
                store_graph(self.root, graph)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_empty_isolates_large_int_and_external_source(self):
        for graph in (extract([], annotations(())), extract([]),
                      extract([edge(1, 2, 2 ** 64), edge(1, 99, 2 ** 64)]),
                      extract([edge(99, 100, 7)])):
            self.assertEqual(load_graph(self.root, store_graph(self.root, graph)), graph)

    def test_failed_publish_and_fsync_leave_previous_entry_intact(self):
        graph = extract()
        key = store_graph(self.root, graph)
        original = (self.root / (key + '.json')).read_bytes()
        changed = extract(created_utc='2026-09-18T00:00:00Z')
        for operation in ('os.link', 'os.fsync'):
            with patch('microduck_connectome.graph_cache.' + operation, side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    store_graph(self.root, changed)
            self.assertEqual(list(self.root.iterdir()), [self.root / (key + '.json')])
            self.assertEqual((self.root / (key + '.json')).read_bytes(), original)
            self.assertEqual(load_graph(self.root, key), graph)

    def test_unselected_source_weight_requires_an_additional_row(self):
        graph = extract([edge(1, 2, 3), edge(1, 99, 7)])
        graph['manifest']['source_raw_weight_sum'] = 11
        with self.assertRaisesRegex(GraphCacheError, 'inconsistent source counts'):
            store_graph(self.root, graph)
        # A matching byte digest must not bypass the same semantic validation.
        data = json.dumps(graph, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('utf-8')
        key = hashlib.sha256(data).hexdigest()
        (self.root / (key + '.json')).write_bytes(data)
        with self.assertRaisesRegex(GraphCacheError, 'inconsistent source counts'):
            load_graph(self.root, key)

    def test_valid_omitted_rows_with_and_without_unselected_sources(self):
        for rows in ([edge(1, 2, 3), edge(1, 99, 7), edge(99, 100, 1)],
                     [edge(1, 2, 3), edge(1, 99, 4), edge(1, 100, 3)]):
            with self.subTest(rows=rows):
                graph = extract(rows)
                self.assertEqual(load_graph(self.root, store_graph(self.root, graph)), graph)

    def test_partial_write_is_never_published(self):
        factory = tempfile.NamedTemporaryFile
        class FailingWrite:
            def __init__(self, *args, **kwargs):
                self.stream = factory(*args, **kwargs)
                self.name = self.stream.name
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def write(self, data):
                self.stream.write(data[:10])
                raise OSError('partial write')
        with patch('microduck_connectome.graph_cache.tempfile.NamedTemporaryFile', FailingWrite):
            with self.assertRaises(OSError):
                store_graph(self.root, extract())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_publish_race_rejects_corrupt_winner(self):
        graph = extract()
        key = graph_cache_key(graph)
        target = self.root / (key + '.json')
        def winner(source, destination):
            target.write_bytes(b'corrupt winner')
            raise FileExistsError('race')
        with patch('microduck_connectome.graph_cache.os.link', side_effect=winner):
            with self.assertRaises(GraphCacheError):
                store_graph(self.root, graph)
        self.assertEqual(target.read_bytes(), b'corrupt winner')
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_publish_race_validates_winner(self):
        graph = extract()
        key = graph_cache_key(graph)
        target = self.root / (key + '.json')
        def winner(source, destination):
            target.write_bytes(Path(source).read_bytes())
            raise FileExistsError('race')
        with patch('microduck_connectome.graph_cache.os.link', side_effect=winner):
            self.assertEqual(store_graph(self.root, graph), key)
        self.assertEqual(load_graph(self.root, key), graph)
        self.assertEqual(list(self.root.iterdir()), [target])


if __name__ == '__main__':
    unittest.main()
