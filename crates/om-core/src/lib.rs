use std::sync::atomic::{AtomicU64, Ordering};

use serde::Serialize;

static NEXT_REQUEST_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Address(String);

impl Address {
    pub fn parse(value: &str) -> Result<Self, AddressError> {
        let Some((scheme, rest)) = value.split_once("://") else {
            return Err(AddressError);
        };
        if scheme != "om" || rest.is_empty() || rest.bytes().any(|byte| byte.is_ascii_whitespace())
        {
            return Err(AddressError);
        }
        let mut segments = rest.split('/');
        let authority = segments.next().unwrap_or_default();
        let path: Vec<_> = segments.collect();
        if authority.is_empty() || path.is_empty() || path.iter().any(|segment| segment.is_empty())
        {
            return Err(AddressError);
        }
        Ok(Self(value.to_owned()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AddressError;

impl std::fmt::Display for AddressError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("address must use om://authority/path form")
    }
}

impl std::error::Error for AddressError {}

pub fn new_request_id() -> String {
    let sequence = NEXT_REQUEST_ID.fetch_add(1, Ordering::Relaxed);
    format!("om-{}-{sequence}", std::process::id())
}

pub fn valid_request_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

#[derive(Debug, Serialize)]
pub struct ErrorEnvelope<'a> {
    pub error: ErrorBody<'a>,
}

#[derive(Debug, Serialize)]
pub struct ErrorBody<'a> {
    pub code: &'a str,
    pub message: &'a str,
}

impl<'a> ErrorEnvelope<'a> {
    pub fn new(code: &'a str, message: &'a str) -> Self {
        Self {
            error: ErrorBody { code, message },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{new_request_id, valid_request_id, Address};

    #[test]
    fn address_accepts_om_authority_and_path() {
        let address = Address::parse("om://demo/model/default").expect("valid address");
        assert_eq!(address.as_str(), "om://demo/model/default");
    }

    #[test]
    fn address_rejects_missing_parts_and_other_schemes() {
        for value in [
            "",
            "https://demo/model",
            "om://",
            "om://demo",
            "om://demo//x",
        ] {
            assert!(Address::parse(value).is_err(), "accepted {value:?}");
        }
    }

    #[test]
    fn request_ids_are_unique_and_header_safe() {
        let first = new_request_id();
        let second = new_request_id();
        assert_ne!(first, second);
        assert!(valid_request_id(&first));
        assert!(!valid_request_id("id\r\ninjected: true"));
        assert!(!valid_request_id(&"x".repeat(65)));
    }
}
