use std::collections::HashMap;
use std::env;
use std::fs;
use std::process::Command;
use std::time::{Duration, Instant};

use biscuit_auth::macros::{authorizer, biscuit, block};
use biscuit_auth::{Algorithm, Biscuit, KeyPair};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use hmac::{Hmac, Mac};
use rand::SeedableRng;
use rand::rngs::StdRng;
use serde::Serialize;
use sha2::{Digest, Sha256};

type HmacSha256 = Hmac<Sha256>;

const CLAIMS: &[u8] = b"tenant=demo;model=om://demo/model/default;budget=100000";
const HMAC_ROOT: [u8; 32] = [0x35; 32];
const BENCH_SEED: [u8; 32] = [0x42; 32];

#[derive(Serialize)]
struct Metadata {
    classification: &'static str,
    platform_scope: &'static str,
    os: &'static str,
    architecture: &'static str,
    kernel: String,
    cpu_model: String,
    allowed_cpu_list: String,
    rustc: String,
    deterministic_seed: &'static str,
    iterations_per_run: usize,
    warmup_iterations_per_run: usize,
    runs_per_cell: usize,
    timing_unit: &'static str,
    cache_definition: &'static str,
    chain_depth_definition: &'static str,
}

#[derive(Serialize)]
struct Run {
    samples_ns: Vec<u64>,
    p50_ns: u64,
    p95_ns: u64,
    p99_ns: u64,
}

#[derive(Serialize)]
struct Cell {
    scheme: &'static str,
    depth: usize,
    token_size_bytes: usize,
    uncached: Vec<Run>,
    cached: Vec<Run>,
}

#[derive(Serialize)]
struct Report {
    metadata: Metadata,
    results: Vec<Cell>,
}

struct HmacToken {
    bytes: Vec<u8>,
}

struct Ed25519Token {
    bytes: Vec<u8>,
    root_public_key: VerifyingKey,
}

struct CacheEntry {
    expires_at: Instant,
    issuer_key_version: u32,
}

fn append_u16(target: &mut Vec<u8>, value: usize) {
    target.extend_from_slice(&(value as u16).to_be_bytes());
}

fn take<'a>(input: &'a [u8], offset: &mut usize, count: usize) -> Option<&'a [u8]> {
    let end = offset.checked_add(count)?;
    let result = input.get(*offset..end)?;
    *offset = end;
    Some(result)
}

fn take_u16(input: &[u8], offset: &mut usize) -> Option<usize> {
    let bytes = take(input, offset, 2)?;
    Some(u16::from_be_bytes([bytes[0], bytes[1]]) as usize)
}

fn hmac_sign(key: &[u8], input: &[u8]) -> [u8; 32] {
    let mut mac = HmacSha256::new_from_slice(key).expect("HMAC accepts any key length");
    mac.update(input);
    mac.finalize().into_bytes().into()
}

fn build_hmac(depth: usize) -> HmacToken {
    let mut bytes = vec![1, depth as u8];
    append_u16(&mut bytes, CLAIMS.len());
    bytes.extend_from_slice(CLAIMS);
    for index in 0..depth {
        let caveat = format!("max_tokens<={}", 1000 - index);
        append_u16(&mut bytes, caveat.len());
        bytes.extend_from_slice(caveat.as_bytes());
    }
    let mut signature_input = b"om-sanchar-hmac-v1\0".to_vec();
    signature_input.extend_from_slice(CLAIMS);
    let mut signature = hmac_sign(&HMAC_ROOT, &signature_input);
    for index in 0..depth {
        let caveat = format!("max_tokens<={}", 1000 - index);
        signature = hmac_sign(&signature, caveat.as_bytes());
    }
    bytes.extend_from_slice(&signature);
    HmacToken { bytes }
}

fn verify_hmac(bytes: &[u8]) -> bool {
    let mut offset = 0;
    let Some(header) = take(bytes, &mut offset, 2) else {
        return false;
    };
    if header[0] != 1 {
        return false;
    }
    let depth = header[1] as usize;
    if depth > 8 {
        return false;
    }
    let Some(claims_length) = take_u16(bytes, &mut offset) else {
        return false;
    };
    let Some(claims) = take(bytes, &mut offset, claims_length) else {
        return false;
    };
    if claims != CLAIMS {
        return false;
    }
    let mut caveats = Vec::with_capacity(depth);
    let mut current_ceiling = 1000usize;
    for _ in 0..depth {
        let Some(length) = take_u16(bytes, &mut offset) else {
            return false;
        };
        let Some(caveat) = take(bytes, &mut offset, length) else {
            return false;
        };
        let Some(limit_text) = caveat.strip_prefix(b"max_tokens<=") else {
            return false;
        };
        let Ok(limit_text) = std::str::from_utf8(limit_text) else {
            return false;
        };
        let Ok(limit) = limit_text.parse::<usize>() else {
            return false;
        };
        if limit > current_ceiling {
            return false;
        }
        current_ceiling = limit;
        caveats.push(caveat);
    }
    let Some(final_signature) = take(bytes, &mut offset, 32) else {
        return false;
    };
    if offset != bytes.len() {
        return false;
    }
    let mut signature_input = b"om-sanchar-hmac-v1\0".to_vec();
    signature_input.extend_from_slice(claims);
    let mut signature = hmac_sign(&HMAC_ROOT, &signature_input);
    for caveat in caveats {
        signature = hmac_sign(&signature, caveat);
    }
    let mut mac = HmacSha256::new_from_slice(&signature).expect("HMAC accepts any key length");
    mac.update(b"om-sanchar-final-signature-check");
    let expected = mac.finalize().into_bytes();
    let mut check =
        HmacSha256::new_from_slice(final_signature).expect("HMAC accepts any key length");
    check.update(b"om-sanchar-final-signature-check");
    check.verify_slice(&expected).is_ok()
}

fn deterministic_signing_key(label: &[u8]) -> SigningKey {
    let seed: [u8; 32] = Sha256::digest(label).into();
    SigningKey::from_bytes(&seed)
}

fn ed_link_message(index: usize, caveat: &[u8], next_key: &[u8; 32]) -> Vec<u8> {
    let mut message = b"om-sanchar-ed25519-link-v1\0".to_vec();
    message.extend_from_slice(&(index as u32).to_be_bytes());
    append_u16(&mut message, caveat.len());
    message.extend_from_slice(caveat);
    message.extend_from_slice(next_key);
    message
}

fn build_ed25519(depth: usize) -> Ed25519Token {
    let root = deterministic_signing_key(b"om-sanchar-root");
    let delegates: Vec<SigningKey> = (0..=depth)
        .map(|index| deterministic_signing_key(format!("om-sanchar-delegate-{index}").as_bytes()))
        .collect();
    let root_public_key = root.verifying_key();
    let first_key = delegates[0].verifying_key().to_bytes();
    let mut root_message = b"om-sanchar-ed25519-authority-v1\0".to_vec();
    append_u16(&mut root_message, CLAIMS.len());
    root_message.extend_from_slice(CLAIMS);
    root_message.extend_from_slice(&first_key);
    let root_signature = root.sign(&root_message).to_bytes();

    let mut bytes = vec![1, depth as u8];
    append_u16(&mut bytes, CLAIMS.len());
    bytes.extend_from_slice(CLAIMS);
    bytes.extend_from_slice(&first_key);
    bytes.extend_from_slice(&root_signature);
    for index in 0..depth {
        let caveat = format!("max_tokens<={}", 1000 - index);
        let next_key = delegates[index + 1].verifying_key().to_bytes();
        let message = ed_link_message(index, caveat.as_bytes(), &next_key);
        let signature = delegates[index].sign(&message).to_bytes();
        append_u16(&mut bytes, caveat.len());
        bytes.extend_from_slice(caveat.as_bytes());
        bytes.extend_from_slice(&next_key);
        bytes.extend_from_slice(&signature);
    }
    Ed25519Token {
        bytes,
        root_public_key,
    }
}

fn verify_ed25519(bytes: &[u8], root_public_key: &VerifyingKey) -> bool {
    let mut offset = 0;
    let Some(header) = take(bytes, &mut offset, 2) else {
        return false;
    };
    if header[0] != 1 {
        return false;
    }
    let depth = header[1] as usize;
    if depth > 8 {
        return false;
    }
    let Some(claims_length) = take_u16(bytes, &mut offset) else {
        return false;
    };
    let Some(claims) = take(bytes, &mut offset, claims_length) else {
        return false;
    };
    if claims != CLAIMS {
        return false;
    }
    let Some(first_key_bytes) = take(bytes, &mut offset, 32) else {
        return false;
    };
    let Ok(first_key_array) = <[u8; 32]>::try_from(first_key_bytes) else {
        return false;
    };
    let Some(root_signature_bytes) = take(bytes, &mut offset, 64) else {
        return false;
    };
    let Ok(root_signature_array) = <[u8; 64]>::try_from(root_signature_bytes) else {
        return false;
    };
    let Ok(first_key) = VerifyingKey::from_bytes(&first_key_array) else {
        return false;
    };
    let root_signature = Signature::from_bytes(&root_signature_array);
    let mut root_message = b"om-sanchar-ed25519-authority-v1\0".to_vec();
    append_u16(&mut root_message, claims.len());
    root_message.extend_from_slice(claims);
    root_message.extend_from_slice(first_key_bytes);
    if root_public_key
        .verify(&root_message, &root_signature)
        .is_err()
    {
        return false;
    }
    let mut current_key = first_key;
    let mut current_ceiling = 1000usize;
    for index in 0..depth {
        let Some(caveat_length) = take_u16(bytes, &mut offset) else {
            return false;
        };
        let Some(caveat) = take(bytes, &mut offset, caveat_length) else {
            return false;
        };
        let Some(next_key_bytes) = take(bytes, &mut offset, 32) else {
            return false;
        };
        let Ok(next_key_array) = <[u8; 32]>::try_from(next_key_bytes) else {
            return false;
        };
        let Some(signature_bytes) = take(bytes, &mut offset, 64) else {
            return false;
        };
        let Ok(signature_array) = <[u8; 64]>::try_from(signature_bytes) else {
            return false;
        };
        let Ok(next_key) = VerifyingKey::from_bytes(&next_key_array) else {
            return false;
        };
        let Some(limit_text) = caveat.strip_prefix(b"max_tokens<=") else {
            return false;
        };
        let Ok(limit_text) = std::str::from_utf8(limit_text) else {
            return false;
        };
        let Ok(limit) = limit_text.parse::<usize>() else {
            return false;
        };
        if limit > current_ceiling {
            return false;
        }
        current_ceiling = limit;
        let message = ed_link_message(index, caveat, next_key_bytes.try_into().unwrap());
        let signature = Signature::from_bytes(&signature_array);
        if current_key.verify(&message, &signature).is_err() {
            return false;
        }
        current_key = next_key;
    }
    offset == bytes.len()
}

fn build_biscuit(depth: usize) -> (Vec<u8>, biscuit_auth::PublicKey) {
    let mut rng = StdRng::from_seed(BENCH_SEED);
    let root = KeyPair::new_with_rng(Algorithm::Ed25519, &mut rng);
    let mut token = biscuit!(r#"right("om-sanchar", "invoke"); request_tokens(900);"#)
        .build_with_rng(
            &root,
            biscuit_auth::datalog::SymbolTable::new(),
            &mut rng,
        )
        .expect("build Biscuit authority block");
    for index in 1..=depth {
        let limit = (1000 - index) as i64;
        let next_key = KeyPair::new_with_rng(Algorithm::Ed25519, &mut rng);
        token = token
            .append_with_keypair(
                &next_key,
                block!(
                r#"check if request_tokens($n), $n <= {limit};"#,
                limit = limit
                ),
            )
            .expect("append Biscuit attenuation block");
    }
    (token.to_vec().expect("serialize Biscuit"), root.public())
}

fn verify_biscuit(bytes: &[u8], root: &biscuit_auth::PublicKey) -> bool {
    let Ok(token) = Biscuit::from(bytes, root.clone()) else {
        return false;
    };
    let Ok(mut authorizer) =
        authorizer!(r#"allow if right("om-sanchar", "invoke");"#).build(&token)
    else {
        return false;
    };
    authorizer.authorize().is_ok()
}

fn hash_token(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn percentile(sorted: &[u64], numerator: usize, denominator: usize) -> u64 {
    sorted[((sorted.len() - 1) * numerator) / denominator]
}

fn token_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        encoded.push(HEX[(byte >> 4) as usize] as char);
        encoded.push(HEX[(byte & 0x0f) as usize] as char);
    }
    encoded
}

fn measure<F>(
    label: &str,
    token: &[u8],
    mut verify: F,
    iterations: usize,
    run_count: usize,
) -> Vec<Run>
where
    F: FnMut() -> bool,
{
    let mut runs = Vec::with_capacity(run_count);
    for _ in 0..run_count {
        for _ in 0..100 {
            assert!(
                verify(),
                "token verification failed during warmup: {label}; token_hex={}",
                token_hex(token)
            );
        }
        let mut samples_ns = Vec::with_capacity(iterations);
        for _ in 0..iterations {
            let started = Instant::now();
            assert!(
                verify(),
                "token verification failed during measurement: {label}; token_hex={}",
                token_hex(token)
            );
            samples_ns.push(started.elapsed().as_nanos() as u64);
        }
        let mut sorted = samples_ns.clone();
        sorted.sort_unstable();
        runs.push(Run {
            p50_ns: percentile(&sorted, 50, 100),
            p95_ns: percentile(&sorted, 95, 100),
            p99_ns: percentile(&sorted, 99, 100),
            samples_ns,
        });
    }
    runs
}

fn cached_measure(label: &str, bytes: &[u8], iterations: usize, run_count: usize) -> Vec<Run> {
    let digest = hash_token(bytes);
    let mut cache = HashMap::new();
    cache.insert(
        digest,
        CacheEntry {
            expires_at: Instant::now() + Duration::from_secs(600),
            issuer_key_version: 1,
        },
    );
    measure(
        label,
        bytes,
        || {
            cache.get(&hash_token(bytes)).is_some_and(|entry| {
                entry.issuer_key_version == 1 && Instant::now() < entry.expires_at
            })
        },
        iterations,
        run_count,
    )
}

fn command_output(program: &str, args: &[&str]) -> String {
    Command::new(program)
        .args(args)
        .output()
        .ok()
        .filter(|output| output.status.success())
        .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_string())
        .unwrap_or_else(|| "unavailable".to_string())
}

fn read_first_line(path: &str, prefix: &str) -> String {
    fs::read_to_string(path)
        .ok()
        .and_then(|data| {
            data.lines()
                .find(|line| line.trim_start().starts_with(prefix))
                .map(str::trim)
                .map(|line| line.split_once(':').map_or(line, |(_, value)| value.trim()))
                .map(str::to_string)
        })
        .unwrap_or_else(|| "unavailable".to_string())
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let iterations = args
        .get(1)
        .and_then(|value| value.parse().ok())
        .unwrap_or(1000);
    let run_count = args
        .get(2)
        .and_then(|value| value.parse().ok())
        .unwrap_or(10);
    let output_path = args
        .get(3)
        .map(String::as_str)
        .unwrap_or("bench/results/capability-token-rust.json");
    assert!(
        iterations > 0 && run_count > 0,
        "iterations and run count must be positive"
    );

    let mut results = Vec::with_capacity(24);
    for depth in 1..=8 {
        let hmac = build_hmac(depth);
        results.push(Cell {
            scheme: "hmac-chain",
            depth,
            token_size_bytes: hmac.bytes.len(),
            uncached: measure(
                &format!("hmac-chain depth={depth} uncached"),
                &hmac.bytes,
                || verify_hmac(&hmac.bytes),
                iterations,
                run_count,
            ),
            cached: cached_measure(
                &format!("hmac-chain depth={depth} cached"),
                &hmac.bytes,
                iterations,
                run_count,
            ),
        });

        let (biscuit_bytes, biscuit_root) = build_biscuit(depth);
        results.push(Cell {
            scheme: "biscuit-auth-6.0.0",
            depth,
            token_size_bytes: biscuit_bytes.len(),
            uncached: measure(
                &format!("biscuit-auth depth={depth} uncached"),
                &biscuit_bytes,
                || verify_biscuit(&biscuit_bytes, &biscuit_root),
                iterations,
                run_count,
            ),
            cached: cached_measure(
                &format!("biscuit-auth depth={depth} cached"),
                &biscuit_bytes,
                iterations,
                run_count,
            ),
        });

        let ed25519 = build_ed25519(depth);
        results.push(Cell {
            scheme: "ed25519-attenuation-chain",
            depth,
            token_size_bytes: ed25519.bytes.len(),
            uncached: measure(
                &format!("ed25519-chain depth={depth} uncached"),
                &ed25519.bytes,
                || verify_ed25519(&ed25519.bytes, &ed25519.root_public_key),
                iterations,
                run_count,
            ),
            cached: cached_measure(
                &format!("ed25519-chain depth={depth} cached"),
                &ed25519.bytes,
                iterations,
                run_count,
            ),
        });
    }

    let metadata = Metadata {
        classification: "measured",
        platform_scope: "WSL2 development-only; not a qualifying native Linux host result",
        os: env::consts::OS,
        architecture: env::consts::ARCH,
        kernel: command_output("uname", &["-r"]),
        cpu_model: read_first_line("/proc/cpuinfo", "model name"),
        allowed_cpu_list: read_first_line("/proc/self/status", "Cpus_allowed_list"),
        rustc: command_output("rustc", &["--version"]),
        deterministic_seed: "Biscuit uses StdRng seeded with 0x42 repeated to 32 bytes for issuer and attenuation keys; Ed25519 keys are SHA-256-derived; HMAC root is 0x35 repeated to 32 bytes",
        iterations_per_run: iterations,
        warmup_iterations_per_run: 100,
        runs_per_cell: run_count,
        timing_unit: "nanoseconds per verification; raw sample arrays retained",
        cache_definition: "SHA-256 token hash plus in-process hash-map lookup, monotonic 10-minute TTL, and issuer-key version check; excludes cache insertion and internal-credential minting",
        chain_depth_definition: "number of appended attenuation caveats/blocks after the authority claim",
    };
    let report = Report { metadata, results };
    let serialized = serde_json::to_string_pretty(&report).expect("serialize benchmark report");
    fs::write(output_path, serialized + "\n").expect("write benchmark report");
    println!("wrote {output_path}");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_schemes_verify_at_each_registered_depth() {
        for depth in 1..=8 {
            let hmac = build_hmac(depth);
            assert!(verify_hmac(&hmac.bytes));

            let (biscuit_bytes, biscuit_root) = build_biscuit(depth);
            assert!(verify_biscuit(&biscuit_bytes, &biscuit_root));

            let ed25519 = build_ed25519(depth);
            assert!(verify_ed25519(&ed25519.bytes, &ed25519.root_public_key));
        }
    }

    #[test]
    fn all_schemes_reject_tampered_serialized_tokens() {
        let hmac = build_hmac(4);
        let mut tampered_hmac = hmac.bytes.clone();
        *tampered_hmac.last_mut().expect("HMAC signature") ^= 1;
        assert!(!verify_hmac(&tampered_hmac));

        let (biscuit_bytes, biscuit_root) = build_biscuit(4);
        let mut tampered_biscuit = biscuit_bytes;
        *tampered_biscuit.last_mut().expect("Biscuit bytes") ^= 1;
        assert!(!verify_biscuit(&tampered_biscuit, &biscuit_root));

        let ed25519 = build_ed25519(4);
        let mut tampered_ed25519 = ed25519.bytes.clone();
        *tampered_ed25519.last_mut().expect("Ed25519 signature") ^= 1;
        assert!(!verify_ed25519(&tampered_ed25519, &ed25519.root_public_key));
    }

    #[test]
    fn fixed_seed_produces_byte_for_byte_reproducible_tokens() {
        for depth in 1..=8 {
            let first_hmac = build_hmac(depth);
            let second_hmac = build_hmac(depth);
            assert_eq!(first_hmac.bytes, second_hmac.bytes);

            let (first_biscuit, _) = build_biscuit(depth);
            let (second_biscuit, _) = build_biscuit(depth);
            assert_eq!(first_biscuit, second_biscuit);

            let first_ed25519 = build_ed25519(depth);
            let second_ed25519 = build_ed25519(depth);
            assert_eq!(first_ed25519.bytes, second_ed25519.bytes);
        }
    }
}
