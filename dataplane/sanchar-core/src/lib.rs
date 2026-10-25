//! Executable, bounded stream state machine for the Om Sanchar stream contract.
//!
//! This crate owns protocol behavior, not durable storage. A production store
//! can persist these transitions while preserving the same observable rules.

use std::collections::{HashMap, VecDeque};
use std::fmt;
use std::sync::Arc;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StreamState {
    New,
    Open,
    Suspended,
    Completed,
    Failed,
    Cancelled,
}

impl StreamState {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::New => "NEW",
            Self::Open => "OPEN",
            Self::Suspended => "SUSPENDED",
            Self::Completed => "COMPLETED",
            Self::Failed => "FAILED",
            Self::Cancelled => "CANCELLED",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StreamEvent {
    pub seq: u64,
    pub idempotency_key: String,
    pub payload: Vec<u8>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Limits {
    pub buffer_limit: usize,
    pub max_events: usize,
    pub max_payload_bytes: usize,
    pub max_total_payload_bytes: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            buffer_limit: 8,
            max_events: 1024,
            max_payload_bytes: 64 * 1024,
            max_total_payload_bytes: 16 * 1024 * 1024,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StreamError {
    InvalidState,
    InvalidArgument,
    IdempotencyConflict,
    CursorExpired,
    InvalidCursor,
    Backpressure,
    LimitReached,
}

impl StreamError {
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InvalidState | Self::InvalidArgument => "OS-0001",
            Self::IdempotencyConflict => "OS-0401",
            Self::CursorExpired => "OS-0400",
            Self::InvalidCursor => "OS-0402",
            Self::Backpressure => "OS-0403",
            Self::LimitReached => "OS-0404",
        }
    }
}

impl fmt::Display for StreamError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::InvalidState => "operation is not valid in the current stream state",
            Self::InvalidArgument => "stream argument is invalid",
            Self::IdempotencyConflict => "idempotency key was reused with different payload bytes",
            Self::CursorExpired => "requested cursor predates retained data",
            Self::InvalidCursor => "cursor is malformed, regresses, or is ahead of the stream",
            Self::Backpressure => "retained event buffer is full",
            Self::LimitReached => "stream reached a configured finite limit",
        })
    }
}

impl std::error::Error for StreamError {}

/// Single-process state machine. Persistence and cross-process coordination
/// belong to the store that owns this record.
pub struct StreamRecord {
    stream_id: String,
    limits: Limits,
    state: StreamState,
    ack_cursor: u64,
    last_seq: u64,
    retained: VecDeque<Arc<StreamEvent>>,
    idempotency: HashMap<String, Arc<StreamEvent>>,
    total_payload_bytes: usize,
}

impl StreamRecord {
    pub fn new(stream_id: impl Into<String>, limits: Limits) -> Result<Self, StreamError> {
        let stream_id = stream_id.into();
        if stream_id.is_empty()
            || limits.buffer_limit == 0
            || limits.max_events < limits.buffer_limit
            || limits.max_payload_bytes == 0
            || limits.max_total_payload_bytes < limits.max_payload_bytes
        {
            return Err(StreamError::InvalidArgument);
        }
        Ok(Self {
            stream_id,
            limits,
            state: StreamState::New,
            ack_cursor: 0,
            last_seq: 0,
            retained: VecDeque::new(),
            idempotency: HashMap::new(),
            total_payload_bytes: 0,
        })
    }

    pub fn stream_id(&self) -> &str {
        &self.stream_id
    }

    pub const fn state(&self) -> StreamState {
        self.state
    }

    pub const fn ack_cursor(&self) -> u64 {
        self.ack_cursor
    }

    pub const fn last_seq(&self) -> u64 {
        self.last_seq
    }

    pub fn open(&mut self) -> Result<(), StreamError> {
        self.require_state(StreamState::New)?;
        self.state = StreamState::Open;
        Ok(())
    }

    pub fn publish(
        &mut self,
        idempotency_key: &str,
        payload: &[u8],
    ) -> Result<Arc<StreamEvent>, StreamError> {
        self.require_state(StreamState::Open)?;
        if idempotency_key.is_empty() || idempotency_key.len() > 128 {
            return Err(StreamError::InvalidArgument);
        }
        if let Some(existing) = self.idempotency.get(idempotency_key) {
            if existing.payload != payload {
                return Err(StreamError::IdempotencyConflict);
            }
            return Ok(Arc::clone(existing));
        }
        if self.idempotency.len() >= self.limits.max_events
            || payload.len() > self.limits.max_payload_bytes
            || self
                .total_payload_bytes
                .checked_add(payload.len())
                .map_or(true, |total| total > self.limits.max_total_payload_bytes)
        {
            return Err(StreamError::LimitReached);
        }
        if self.retained.len() >= self.limits.buffer_limit {
            return Err(StreamError::Backpressure);
        }
        let seq = self
            .last_seq
            .checked_add(1)
            .ok_or(StreamError::LimitReached)?;
        let event = Arc::new(StreamEvent {
            seq,
            idempotency_key: idempotency_key.to_owned(),
            payload: payload.to_vec(),
        });
        self.retained.push_back(Arc::clone(&event));
        self.idempotency
            .insert(idempotency_key.to_owned(), Arc::clone(&event));
        self.total_payload_bytes += payload.len();
        self.last_seq = seq;
        Ok(event)
    }

    pub fn acknowledge(&mut self, cursor: u64) -> Result<(), StreamError> {
        self.require_state(StreamState::Open)?;
        if cursor < self.ack_cursor || cursor > self.last_seq {
            return Err(StreamError::InvalidCursor);
        }
        self.ack_cursor = cursor;
        self.retained.retain(|event| event.seq > cursor);
        Ok(())
    }

    pub fn disconnect(&mut self) -> Result<(), StreamError> {
        self.require_state(StreamState::Open)?;
        self.state = StreamState::Suspended;
        Ok(())
    }

    pub fn resume(&mut self, cursor: u64) -> Result<Vec<Arc<StreamEvent>>, StreamError> {
        self.require_state(StreamState::Suspended)?;
        if cursor > self.last_seq {
            return Err(StreamError::InvalidCursor);
        }
        if cursor < self.ack_cursor {
            return Err(StreamError::CursorExpired);
        }
        let replay = self
            .retained
            .iter()
            .filter(|event| event.seq > cursor)
            .cloned()
            .collect();
        self.state = StreamState::Open;
        Ok(replay)
    }

    pub fn complete(&mut self) -> Result<(), StreamError> {
        self.finish(StreamState::Completed)
    }

    pub fn fail(&mut self) -> Result<(), StreamError> {
        self.finish(StreamState::Failed)
    }

    pub fn cancel(&mut self) -> Result<(), StreamError> {
        self.finish(StreamState::Cancelled)
    }

    fn finish(&mut self, final_state: StreamState) -> Result<(), StreamError> {
        if self.state != StreamState::Open && self.state != StreamState::Suspended {
            return Err(StreamError::InvalidState);
        }
        self.state = final_state;
        Ok(())
    }

    fn require_state(&self, expected: StreamState) -> Result<(), StreamError> {
        if self.state == expected {
            Ok(())
        } else {
            Err(StreamError::InvalidState)
        }
    }
}
