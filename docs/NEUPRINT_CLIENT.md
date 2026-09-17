# P1-01 pinned neuPrint client

From the repository root, with Python 3.10+ (standard library only):

```sh
python -m unittest discover -s tests -p 'test_*.py'
python -m microduck_connectome.neuprint_client --code-commit <full-clean-checkout-Git-SHA>
```

The live command requires `NEUPRINT_APPLICATION_CREDENTIALS` already loaded into the process environment from secret storage. Supply the raw token, without a `Bearer ` prefix. The module does not load `.env`, accept command-line credentials, or write files. On Thor, the PM loads credentials there; never copy them locally. Do not enable HTTP wire logging or traceback-local capture when using credentials.

The endpoint is fixed to `https://neuprint.janelia.org/api/custom/custom`, the dataset to `male-cns:v1.0`, and the query to `dna02-body-ids-v1`. It selects neurons with type `DNa02` and returns only body IDs. The client uses the read-only custom-query service, JSON request/response format, and bearer authentication described in the [official API specification](https://neuprint.janelia.org/api/help/swagger.yaml). There is no arbitrary-query or write API.

```python
from microduck_connectome.neuprint_client import NeuprintClient

result = NeuprintClient(timeout_seconds=20).fetch_dna02()
assert result.body_ids == (10360, 523769)  # pinned smoke expectation
evidence = result.provenance(code_commit="<full-clean-checkout-Git-SHA>")
```

The library returns sorted unique positive integer IDs; it rejects empty results, unexpected columns, malformed rows, and duplicates. The CLI additionally compares the result with `data/manifests/neuprint_dna02_smoke.json`, exits nonzero on drift, and emits JSON provenance on success. The public library intentionally leaves expected-population comparisons to its caller. Neither query success nor these smoke IDs establish anatomical side or biological function.

Provenance records dataset, endpoint, exact query/version/hash, caller-supplied code commit, UTC completion time, result IDs/count, and body-ID hash. Hash serialization is UTF-8 compact JSON of sorted integer IDs with no spaces or trailing newline. The code commit must identify a clean checkout; the module validates its syntax but cannot attest checkout cleanliness. These annotation-only results are not a graph and do not have edge counts/hashes. Full graph provenance belongs to subsequent extraction tasks.

Requests have a finite positive socket-operation timeout (20 seconds by default), a 64 KiB response bound, and no retries. This timeout is not a total wall-clock deadline. All redirects are rejected, preventing Authorization forwarding. HTTP/network/JSON failures expose fixed messages without server text or chained transport exceptions. TLS certificate verification uses standard-library defaults. The module keeps no credential on the client/result object; it necessarily holds the credential briefly in request memory.

Offline tests use mocks and a synthetic sentinel token, covering pinning, timeout propagation, redirect refusal, malformed/oversized responses, ID validation, deterministic hashes, credential-safe exceptions, and CLI smoke-result drift. The initial implementation's offline checks are not authenticated evidence. The PM must run the exact committed code on Thor and retain its redacted JSON provenance before marking P1-01 known-query acceptance met; independent review and phase gates remain separate.
