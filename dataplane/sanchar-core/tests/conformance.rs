use sanchar_core::{Limits, StreamRecord, StreamState};
use serde_json::Value;

const VECTORS: &str = include_str!("../../../spec/conformance/stream-vectors.json");

fn number(value: &Value, field: &str) -> u64 {
    value[field].as_u64().expect("unsigned integer field")
}

fn usize_number(value: &Value, field: &str) -> usize {
    usize::try_from(number(value, field)).expect("limit fits usize")
}

fn state_from_str(value: &str) -> StreamState {
    match value {
        "NEW" => StreamState::New,
        "OPEN" => StreamState::Open,
        "SUSPENDED" => StreamState::Suspended,
        "COMPLETED" => StreamState::Completed,
        "FAILED" => StreamState::Failed,
        "CANCELLED" => StreamState::Cancelled,
        _ => panic!("unknown state {value}"),
    }
}

#[test]
fn shared_json_vectors_match_rust_state_machine() {
    let vectors: Value = serde_json::from_str(VECTORS).expect("valid stream vectors");
    for vector in vectors.as_array().expect("vector list") {
        let name = vector["name"].as_str().expect("vector name");
        let config = &vector["limits"];
        let limits = Limits {
            buffer_limit: usize_number(config, "bufferLimit"),
            max_events: usize_number(config, "maxEvents"),
            max_payload_bytes: usize_number(config, "maxPayloadBytes"),
            max_total_payload_bytes: usize_number(config, "maxTotalPayloadBytes"),
        };
        let mut stream = StreamRecord::new(name, limits).expect("valid limits");

        for operation in vector["operations"].as_array().expect("operations") {
            let op = operation["op"].as_str().expect("operation name");
            let outcome = match op {
                "open" => stream.open().map(|()| None),
                "publish" => stream
                    .publish(
                        operation["key"].as_str().expect("key"),
                        operation["payload"].as_str().expect("payload").as_bytes(),
                    )
                    .map(|event| Some(vec![event.seq])),
                "ack" => stream
                    .acknowledge(number(operation, "cursor"))
                    .map(|()| None),
                "disconnect" => stream.disconnect().map(|()| None),
                "resume" => stream
                    .resume(number(operation, "cursor"))
                    .map(|events| Some(events.iter().map(|event| event.seq).collect())),
                "complete" => stream.complete().map(|()| None),
                "fail" => stream.fail().map(|()| None),
                "cancel" => stream.cancel().map(|()| None),
                "state" => Ok(None),
                _ => panic!("{name}: unknown operation {op}"),
            };

            if let Some(expected_code) = operation["expectError"].as_str() {
                let error = outcome.expect_err("operation should fail");
                assert_eq!(error.code(), expected_code, "{name}: {op}");
            } else {
                let result = outcome.unwrap_or_else(|error| panic!("{name}: {op}: {error}"));
                if let Some(expected_seq) = operation["expectSeq"].as_u64() {
                    assert_eq!(
                        result.as_ref().expect("publish result").as_slice(),
                        &[expected_seq],
                        "{name}"
                    );
                }
                if let Some(expected_seqs) = operation["expectSeqs"].as_array() {
                    let expected: Vec<u64> = expected_seqs
                        .iter()
                        .map(|seq| seq.as_u64().expect("sequence"))
                        .collect();
                    assert_eq!(result.expect("resume result"), expected, "{name}");
                }
            }

            if let Some(expected_state) = operation["expectState"].as_str() {
                assert_eq!(stream.state(), state_from_str(expected_state), "{name}");
                assert_eq!(
                    stream.last_seq(),
                    number(operation, "expectLastSeq"),
                    "{name}"
                );
                assert_eq!(
                    stream.ack_cursor(),
                    number(operation, "expectAckCursor"),
                    "{name}"
                );
            }
        }
    }
}

#[test]
fn replay_is_the_exact_contiguous_unacknowledged_suffix() {
    for count in 1..=32_usize {
        for cursor in 0..=count {
            let limits = Limits {
                buffer_limit: count,
                max_events: count,
                max_payload_bytes: 16,
                max_total_payload_bytes: count * 16,
            };
            let mut stream = StreamRecord::new(format!("stream-{count}-{cursor}"), limits)
                .expect("valid limits");
            stream.open().expect("open");
            let published: Vec<_> = (1..=count)
                .map(|seq| {
                    stream
                        .publish(&format!("key-{seq}"), format!("payload-{seq}").as_bytes())
                        .expect("publish")
                })
                .collect();
            stream
                .acknowledge(cursor as u64)
                .expect("acknowledge prefix");
            stream.disconnect().expect("disconnect");

            let replay = stream.resume(cursor as u64).expect("resume");

            let expected: Vec<u64> = ((cursor + 1)..=count).map(|seq| seq as u64).collect();
            assert_eq!(
                replay.iter().map(|event| event.seq).collect::<Vec<_>>(),
                expected
            );
            assert_eq!(stream.ack_cursor(), cursor as u64);
            assert_eq!(stream.last_seq(), count as u64);
            for (index, event) in published.iter().enumerate() {
                let duplicate = stream
                    .publish(&event.idempotency_key, &event.payload)
                    .expect("idempotent retry");
                assert_eq!(duplicate.seq, (index + 1) as u64);
            }
        }
    }
}
