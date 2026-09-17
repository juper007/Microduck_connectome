"""Synthetic fixtures only: identifiers and annotations are not MaleCNS evidence."""

import copy
import json
import unittest

from microduck_connectome.annotations import (
    AnnotationError, DATASET, annotations_from_json, annotations_to_json,
    normalize_annotations,
)

SHA = "a" * 40  # Synthetic provenance for validation only.
NOTE = "Synthetic annotation fixture; no biological evidence"


def row(body_id=2, **changes):
    value = {"bodyId": body_id, "type": "synthetic-type", "instance": "synthetic_R",
             "somaSide": None, "class": "synthetic-class"}
    value.update(changes)
    return value


def normalize(rows, **changes):
    metadata = {"dataset": DATASET, "source_note": NOTE, "extraction_commit": SHA}
    metadata.update(changes)
    return normalize_annotations(rows, **metadata)


class AnnotationTests(unittest.TestCase):
    def test_roundtrip_preserves_metadata_and_provenance(self):
        rows = [row(9, somaSide="right"), row(1, somaSide="left", type="  α-type  ")]
        artifact = normalize(rows)
        self.assertEqual(artifact["dataset"], DATASET)
        self.assertEqual(artifact["source_note"], NOTE)
        self.assertEqual(artifact["extraction_commit"], SHA)
        self.assertEqual(artifact["records"], [
            {"body_id": 1, "cell_type": "  α-type  ", "instance": "synthetic_R",
             "soma_side": "left", "neuron_class": "synthetic-class"},
            {"body_id": 9, "cell_type": "synthetic-type", "instance": "synthetic_R",
             "soma_side": "right", "neuron_class": "synthetic-class"},
        ])
        encoded = annotations_to_json(artifact)
        self.assertEqual(annotations_from_json(encoded), artifact)
        self.assertEqual(annotations_to_json(annotations_from_json(encoded)), encoded)
        self.assertEqual(json.loads(encoded), artifact)

    def test_row_and_key_order_are_irrelevant(self):
        first = normalize([row(12), row(3)])
        second = normalize([dict(reversed(list(row(3).items()))), row(12)])
        self.assertEqual(annotations_to_json(first), annotations_to_json(second))

    def test_input_is_unmodified_and_unaliased(self):
        rows = [row(8), row(1)]
        original = copy.deepcopy(rows)
        artifact = normalize(rows)
        self.assertEqual(rows, original)
        rows[0]["type"] = "changed"
        self.assertEqual(artifact["records"][1]["cell_type"], "synthetic-type")
        artifact["records"][0]["instance"] = "also changed"
        self.assertEqual(rows[1]["instance"], "synthetic_R")

    def test_nulls_and_no_laterality_inference(self):
        artifact = normalize([row(1), row(2, type=None, instance=None, **{"class": None})])
        self.assertIsNone(artifact["records"][0]["soma_side"])
        self.assertEqual(artifact["records"][0]["instance"], "synthetic_R")
        self.assertTrue(all(value is None for key, value in artifact["records"][1].items()
                            if key != "body_id"))

    def test_empty_input_roundtrip(self):
        self.assertEqual(annotations_from_json(annotations_to_json(normalize([]))), normalize([]))

    def test_large_integer_remains_exact(self):
        body_id = 2 ** 63 - 1
        artifact = normalize([row(body_id)])
        self.assertEqual(annotations_from_json(annotations_to_json(artifact))["records"][0]["body_id"], body_id)

    def test_invalid_body_ids(self):
        for value in (True, False, 1.0, "1", 0, -1, 2 ** 63, 10 ** 5000, None, [], float("nan")):
            with self.subTest(value_type=type(value)), self.assertRaisesRegex(AnnotationError, "bodyId"):
                normalize([row(value)])

    def test_duplicates_rejected_even_when_equal(self):
        for duplicate in (row(2), row(2, type="different")):
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(AnnotationError, "duplicated"):
                normalize([row(2), duplicate])

    def test_missing_and_extra_fields_rejected(self):
        for key in row():
            invalid = row()
            del invalid[key]
            with self.subTest(key=key), self.assertRaises(AnnotationError):
                normalize([invalid])
        with self.assertRaises(AnnotationError):
            normalize([row(extra="unmapped annotation")])

    def test_invalid_optional_text_not_discarded(self):
        for key in ("type", "instance", "class"):
            for value in ("", " \t", 0, False, [], {}, "\ud800"):
                with self.subTest(key=key, value=value), self.assertRaises(AnnotationError):
                    normalize([row(**{key: value})])

    def test_unsupported_soma_side_rejected(self):
        for value in ("L", "R", "Left", "unknown", "bilateral", "midline", "", " left", 0, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(AnnotationError, "somaSide"):
                normalize([row(somaSide=value)])

    def test_malformed_containers(self):
        for value in (None, {}, "rows", 1, iter([])):
            with self.subTest(value=type(value)), self.assertRaises(AnnotationError):
                normalize(value)
        for value in (None, [], "row", 1):
            with self.subTest(value=value), self.assertRaises(AnnotationError):
                normalize([value])
        self.assertEqual(normalize((row(),)), normalize([row()]))

    def test_dataset_and_provenance_required(self):
        for key, values in {
            "dataset": (None, "male-cns:v0.9", "male-cns", ""),
            "source_note": (None, "", "  ", 5),
            "extraction_commit": (None, "a" * 39, "A" * 40, "z" * 40, "main", "a" * 40 + "\n"),
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(AnnotationError):
                    normalize([row()], **{key: value})

    def test_modified_artifacts_revalidated_by_writer_and_reader(self):
        valid = normalize([row()])
        invalids = []
        for key, value in (("schema_version", "annotation-v2"), ("dataset", "wrong"),
                           ("source_note", ""), ("extraction_commit", "main"), ("records", {})):
            invalids.append(dict(valid, **{key: value}))
        for key in valid:
            invalid = copy.deepcopy(valid)
            del invalid[key]
            invalids.append(invalid)
        invalids.append(dict(valid, extra=True))
        for key, value in (("body_id", True), ("soma_side", "R"), ("extra", "data")):
            invalid = copy.deepcopy(valid)
            invalid["records"][0][key] = value
            invalids.append(invalid)
        invalid = copy.deepcopy(valid)
        invalid["records"].append(invalid["records"][0].copy())
        invalids.append(invalid)
        for invalid in invalids:
            with self.subTest(invalid=invalid):
                with self.assertRaises(AnnotationError):
                    annotations_to_json(invalid)
                with self.assertRaises(AnnotationError):
                    annotations_from_json(json.dumps(invalid))

    def test_invalid_json_and_ambiguous_keys(self):
        for text in ('', '{', 'null', '[]', 'NaN', 'Infinity', '-Infinity',
                     '{"dataset":"wrong","dataset":"male-cns:v1.0"}',
                     '{"nested":{"body_id":1,"body_id":2}}',
                     annotations_to_json(normalize([row()])).replace('"body_id":2', '"body_id":2.0')):
            with self.subTest(text=text), self.assertRaises(AnnotationError):
                annotations_from_json(text)
        with self.assertRaises(AnnotationError):
            annotations_from_json(b'{}')


if __name__ == "__main__":
    unittest.main()
