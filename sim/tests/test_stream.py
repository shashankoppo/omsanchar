import json
import unittest
from pathlib import Path

from sim.reference.stream import StreamError, StreamRecord

VECTORS = Path(__file__).parents[2] / "spec" / "conformance" / "stream-vectors.json"


class StreamRecordTests(unittest.TestCase):
    def test_shared_conformance_vectors(self):
        for vector in json.loads(VECTORS.read_text(encoding="utf-8")):
            with self.subTest(name=vector["name"]):
                limits = vector["limits"]
                stream = StreamRecord(
                    vector["name"],
                    buffer_limit=limits["bufferLimit"],
                    max_events=limits["maxEvents"],
                    max_payload_bytes=limits["maxPayloadBytes"],
                    max_total_payload_bytes=limits["maxTotalPayloadBytes"],
                )
                for operation in vector["operations"]:
                    self._apply_operation(stream, operation)

    def test_resume_returns_exact_contiguous_suffix_for_all_cursors(self):
        for count in range(1, 17):
            for cursor in range(count + 1):
                with self.subTest(count=count, cursor=cursor):
                    stream = StreamRecord(
                        f"stream-{count}-{cursor}",
                        buffer_limit=count,
                        max_events=count,
                        max_payload_bytes=16,
                        max_total_payload_bytes=count * 16,
                    )
                    stream.open()
                    published = [
                        stream.publish(f"key-{seq}", f"payload-{seq}".encode("ascii")) for seq in range(1, count + 1)
                    ]
                    stream.acknowledge(cursor)
                    stream.disconnect()

                    replay = stream.resume(cursor)

                    self.assertEqual([event.seq for event in replay], list(range(cursor + 1, count + 1)))
                    self.assertEqual(stream.ack_cursor, cursor)
                    self.assertEqual(stream.last_seq, count)
                    self.assertEqual(
                        [stream.publish(event.idempotency_key, event.payload).seq for event in published],
                        list(range(1, count + 1)),
                    )

    def _apply_operation(self, stream, operation):
        op = operation["op"]
        try:
            result = None
            if op == "open":
                stream.open()
            elif op == "publish":
                event = stream.publish(operation["key"], operation["payload"].encode("utf-8"))
                result = [event.seq]
            elif op == "ack":
                stream.acknowledge(operation["cursor"])
            elif op == "disconnect":
                stream.disconnect()
            elif op == "resume":
                result = [event.seq for event in stream.resume(operation["cursor"])]
            elif op == "complete":
                stream.complete()
            elif op == "fail":
                stream.fail()
            elif op == "cancel":
                stream.cancel()
            elif op != "state":
                self.fail(f"unknown conformance operation: {op}")
        except StreamError as error:
            self.assertEqual(error.code, operation.get("expectError"), op)
        else:
            self.assertNotIn("expectError", operation, op)
            if "expectSeq" in operation:
                self.assertEqual(result, [operation["expectSeq"]], op)
            if "expectSeqs" in operation:
                self.assertEqual(result, operation["expectSeqs"], op)

        if "expectState" in operation:
            self.assertEqual(stream.state.value, operation["expectState"])
            self.assertEqual(stream.last_seq, operation["expectLastSeq"])
            self.assertEqual(stream.ack_cursor, operation["expectAckCursor"])


if __name__ == "__main__":
    unittest.main()
