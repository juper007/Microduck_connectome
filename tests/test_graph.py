"""Offline graph API tests; synthetic fixtures do not assert biological function."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.graph_cache import GraphCacheError, graph_cache_key, store_graph
from test_connectivity import annotations, edge, extract


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.artifact = extract([edge(2, 1, 4), edge(1, 2, 3), edge(1, 1, 2),
                                 edge(1, 99, 5)], annotations((3, 2, 1)))
        self.graph = ConnectomeGraph(self.artifact)

    def test_order_direction_and_weights(self):
        graph = self.graph
        self.assertEqual(graph.body_ids, (1, 2, 3))
        self.assertEqual(tuple(n['body_id'] for n in graph.nodes()), graph.body_ids)
        self.assertEqual([(e['source_body_id'], e['target_body_id']) for e in graph.edges()],
                         [(1, 1), (1, 2), (2, 1)])
        self.assertEqual([e['source_body_id'] for e in graph.incoming(1)], [1, 2])
        self.assertEqual([e['target_body_id'] for e in graph.outgoing(1)], [1, 2])
        self.assertEqual(graph.edge(1, 2)['normalized_weight'], .3)
        self.assertEqual(graph.edge(2, 1)['raw_synapse_weight'], 4)
        self.assertEqual(graph.edge(2, 1)['normalized_weight'], 1.)
        self.assertEqual(graph.edge(1, 2), self.artifact['edges'][1])
        self.assertIsNone(graph.edge(2, 3))
        self.assertEqual(graph.incoming(3), ())
        self.assertEqual(graph.outgoing(3), ())

    def test_exact_type_and_explicit_unknown(self):
        self.assertEqual(self.graph.select_type('synthetic-1'), (1,))
        self.assertEqual(self.graph.select_type(None), (3,))
        for name in ('missing', 'Synthetic-1', ' synthetic-1 ', 'unknown'):
            self.assertEqual(self.graph.select_type(name), ())
        for name in (True, 1, [], {}, '', ' ', '\ud800'):
            with self.subTest(name=repr(name)), self.assertRaises(ValueError):
                self.graph.select_type(name)
        annotation = annotations((3, 2, 1))
        annotation['records'][1]['cell_type'] = 'synthetic-1'
        graph = ConnectomeGraph(extract([], annotation))
        self.assertEqual(graph.select_type('synthetic-1'), (1, 2))

    def test_validation_uses_cache_boundary(self):
        with patch('microduck_connectome.graph.graph_cache_key', wraps=graph_cache_key) as validate:
            ConnectomeGraph(self.artifact)
            validate.assert_called_once()
        for artifact in ({}, None, {'schema_version': 'future'}):
            with self.assertRaises(GraphCacheError):
                ConnectomeGraph(artifact)
        malformed = copy.deepcopy(self.artifact)
        malformed['edges'][0]['normalized_weight'] = .99
        with self.assertRaises(GraphCacheError):
            ConnectomeGraph(malformed)

    def test_inputs_and_every_record_result_are_detached(self):
        expected = copy.deepcopy(self.artifact)
        self.artifact['annotations']['records'][0]['cell_type'] = 'changed'
        self.artifact['edges'][0]['raw_synapse_weight'] = 999
        self.artifact['full_outgoing_sums'][0]['raw_weight_sum'] = 999
        self.artifact['manifest']['seed_populations'].append('changed')
        graph = self.graph
        view = graph.induced([1, 2])
        for item in (graph.node(1), graph.nodes()[0], graph.edge(1, 1), graph.edges()[0],
                     graph.incoming(1)[0], graph.outgoing(1)[0], view.node(1), view.edge(1, 1)):
            item.clear()
        graph.root_manifest['seed_populations'].append('changed')
        view.root_manifest.clear()
        graph.annotation_provenance.clear()
        self.assertEqual(graph.nodes(), tuple(expected['annotations']['records']))
        self.assertEqual(graph.edges(), tuple(expected['edges']))
        self.assertEqual(view.edge(1, 1), expected['edges'][0])
        self.assertEqual(graph.full_outgoing_sum(1), 10)
        self.assertEqual(graph.root_manifest, expected['manifest'])
        self.assertEqual(graph.annotation_provenance['source_note'],
                         expected['annotations']['source_note'])
        self.assertEqual(graph.root_key, graph_cache_key(expected))
        for attribute in ('body_ids', 'root_key', 'root_manifest', 'annotation_provenance'):
            with self.assertRaises(AttributeError):
                setattr(graph, attribute, None)

    def test_invalid_and_missing_ids_across_queries(self):
        queries = (self.graph.node, self.graph.incoming, self.graph.outgoing,
                   self.graph.full_outgoing_sum, lambda x: self.graph.edge(x, 1),
                   lambda x: self.graph.edge(1, x), lambda x: self.graph.induced([x]))
        for query in queries:
            for bad in (True, False, '1', 1., None, [], 0, -1, 2 ** 63):
                with self.subTest(query=query, bad=bad), self.assertRaises(ValueError):
                    query(bad)
            with self.assertRaises(KeyError):
                query(99)
        # Validation happens before set deduplication (True must not alias 1).
        with self.assertRaises(ValueError):
            self.graph.induced([1, True])

    def test_nested_views_preserve_identity_and_denominators(self):
        view = self.graph.induced(iter([3, 2, 1, 2]))
        self.assertEqual(view.body_ids, (1, 2, 3))
        nested = view.induced([3, 1])
        self.assertEqual(nested.body_ids, (1, 3))
        self.assertEqual(nested.edges(), (self.graph.edge(1, 1),))
        self.assertEqual(nested.full_outgoing_sum(1), 10)
        self.assertEqual(nested.edge(1, 1)['normalized_weight'], .2)
        self.assertEqual(nested.full_outgoing_sum(3), 0)
        self.assertEqual(nested.select_type('synthetic-2'), ())
        self.assertEqual(nested.root_key, self.graph.root_key)
        self.assertEqual(nested.root_manifest, self.graph.root_manifest)
        self.assertEqual(nested.root_manifest['node_count'], 3)
        self.assertEqual(nested.annotation_provenance, self.graph.annotation_provenance)
        with self.assertRaises(KeyError):
            nested.induced([2])
        with self.assertRaises(KeyError):
            nested.node(2)

    def test_empty_and_singleton(self):
        for graph in (ConnectomeGraph(extract([], annotations(()))), self.graph.induced([])):
            self.assertEqual(graph.body_ids, ())
            self.assertEqual(graph.nodes(), ())
            self.assertEqual(graph.edges(), ())
            self.assertEqual(graph.select_type(None), ())
            self.assertEqual(graph.induced([]).body_ids, ())
        singleton = self.graph.induced([3])
        self.assertEqual(singleton.body_ids, (3,))
        self.assertEqual(singleton.edges(), ())
        self.assertEqual(singleton.select_type(None), (3,))
        self.assertEqual(self.graph.induced([1]).edges(), (self.graph.edge(1, 1),))

    def test_large_exact_ids_and_weights(self):
        large = 2 ** 63 - 1
        weight = 2 ** 80 + 1
        graph = ConnectomeGraph(extract([edge(large, 1, weight), edge(large, 99, weight)],
                                       annotations((large, 1))))
        self.assertEqual(graph.body_ids, (1, large))
        view = graph.induced([large, 1])
        self.assertEqual(view.full_outgoing_sum(large), 2 * weight)
        self.assertEqual(view.edge(large, 1)['raw_synapse_weight'], weight)
        self.assertEqual(view.edge(large, 1)['normalized_weight'], .5)

    def test_cache_key_integrity_and_real_fixture(self):
        artifact = json.loads((Path(__file__).resolve().parents[1] /
                               'docs/tasks/P1-03-real-graph.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            key = store_graph(directory, artifact)
            graph = ConnectomeGraph.from_cache(directory, key)
            self.assertEqual(graph.root_key, key)
            self.assertEqual(graph.edges(), tuple(artifact['edges']))
            selected = graph.body_ids[:2]
            view = graph.induced(reversed(selected)).induced(selected)
            self.assertEqual(view.root_key, key)
            self.assertEqual(view.root_manifest, artifact['manifest'])
            for row in view.edges():
                self.assertEqual(row, graph.edge(row['source_body_id'], row['target_body_id']))
            for body_id in selected:
                self.assertEqual(view.full_outgoing_sum(body_id), graph.full_outgoing_sum(body_id))
            with self.assertRaises(FileNotFoundError):
                ConnectomeGraph.from_cache(directory, '0' * 64)
            with self.assertRaises(GraphCacheError):
                ConnectomeGraph.from_cache(directory, '../bad')
            (Path(directory) / (key + '.json')).write_text('{}', encoding='utf-8')
            with self.assertRaises(GraphCacheError):
                ConnectomeGraph.from_cache(directory, key)


if __name__ == '__main__':
    unittest.main()
