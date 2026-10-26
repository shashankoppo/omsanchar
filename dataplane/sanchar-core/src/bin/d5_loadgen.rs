//! Rust open-loop HTTP load generator for the registered D5 matrix.
//!
//! Usage: d5_loadgen URL WORKLOAD RATE_RPS DURATION_SECS MAX_IN_FLIGHT OUTPUT.json [CA.pem]

use std::env;
use std::fs;
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

use hdrhistogram::Histogram;
use reqwest::{Certificate, Client, Method, RequestBuilder, Url};
use serde::Serialize;
use serde_json::json;
use tokio::task::JoinSet;
use tokio::time::{sleep_until, Instant as TokioInstant};

static REQUEST_ID: AtomicU64 = AtomicU64::new(1);
const HISTOGRAM_MAX_NS: u64 = 3_600_000_000_000;

#[derive(Clone, Copy, Debug)]
enum Workload {
    Sse500,
    Mcp,
    Fanout,
}

impl Workload {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "sse500" => Ok(Self::Sse500),
            "mcp" => Ok(Self::Mcp),
            "fanout" => Ok(Self::Fanout),
            _ => Err(format!(
                "unsupported workload {value:?}; use sse500, mcp, or fanout"
            )),
        }
    }

    fn name(self) -> &'static str {
        match self {
            Self::Sse500 => "sse500",
            Self::Mcp => "mcp",
            Self::Fanout => "fanout",
        }
    }
}

#[derive(Serialize)]
struct Sample {
    sequence: u64,
    scheduled_offset_ns: u64,
    dispatch_lag_ns: u64,
    response_latency_from_schedule_ns: u64,
    status: Option<u16>,
    error: Option<String>,
}

#[derive(Serialize)]
struct Percentile {
    percentile: f64,
    value_ns: u64,
}

#[derive(Serialize)]
struct Report {
    classification: &'static str,
    platform_scope: &'static str,
    date_utc: String,
    host: String,
    rustc_version: String,
    cargo_version: String,
    reqwest_version: &'static str,
    hdrhistogram_version: &'static str,
    endpoint: String,
    workload: &'static str,
    offered_rate_rps: u64,
    planned_duration_seconds: u64,
    max_in_flight: usize,
    tls: bool,
    offered_arrivals: u64,
    started_requests: u64,
    peak_in_flight_observed: usize,
    completed_requests: u64,
    dropped_at_concurrency_cap: u64,
    late_dispatches_over_1ms: u64,
    http_or_transport_errors: u64,
    hdrhistogram_significant_digits: u8,
    hdrhistogram_total_count: u64,
    hdrhistogram_percentiles: Vec<Percentile>,
    hdrhistogram_percentile_distribution: Vec<Percentile>,
    client_process_peak_rss_bytes: Option<u64>,
    target_cpu_seconds_per_completed_request: Option<f64>,
    target_resident_memory_bytes: Option<u64>,
    kernel: String,
    cpu_model: String,
    cpu_frequency_mhz_snapshot: String,
    allowed_cpu_list: String,
    cpu_governor: String,
    cgroup_cpu_max: String,
    cgroup_memory_max: String,
    pinning: &'static str,
    exact_command: String,
    raw_samples: Vec<Sample>,
}

fn read_first_line(path: &str, prefix: Option<&str>) -> String {
    fs::read_to_string(path)
        .ok()
        .and_then(|contents| {
            contents
                .lines()
                .find(|line| prefix.is_none_or(|wanted| line.trim_start().starts_with(wanted)))
                .map(str::trim)
                .map(str::to_owned)
        })
        .unwrap_or_else(|| "unavailable".to_string())
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

fn process_peak_rss_bytes() -> Option<u64> {
    fs::read_to_string("/proc/self/status")
        .ok()?
        .lines()
        .find_map(|line| {
            line.strip_prefix("VmHWM:")?
                .split_whitespace()
                .next()?
                .parse::<u64>()
                .ok()
        })
        .map(|kib| kib * 1024)
}

fn arrival_at(start: Instant, period_ns: u64, sequence: u64) -> Instant {
    start + Duration::from_nanos(period_ns.saturating_mul(sequence))
}

fn build_request(
    client: &Client,
    endpoint: &Url,
    workload: Workload,
    sequence: u64,
) -> RequestBuilder {
    let mut url = endpoint.clone();
    let path = match workload {
        Workload::Sse500 => "/v1/chat/completions",
        Workload::Mcp => "/mcp",
        Workload::Fanout => "/fanout?n=16",
    };
    url.set_path(path.split('?').next().unwrap_or(path));
    url.set_query(path.split_once('?').map(|(_, query)| query));
    match workload {
        Workload::Sse500 => client.request(Method::POST, url).json(&json!({
            "model": "om://d5/mock",
            "messages": [{"role": "user", "content": "fixed D5 payload"}],
            "stream": true,
            "idempotency_key": format!("d5-{sequence}"),
            "max_tokens": 500
        })),
        Workload::Mcp => client.request(Method::POST, url).json(&json!({
            "jsonrpc": "2.0",
            "id": sequence,
            "method": "tools/call",
            "params": {"name": "mock", "arguments": {"fixed": true}}
        })),
        Workload::Fanout => client.get(url),
    }
}

async fn issue(
    client: Client,
    endpoint: Url,
    workload: Workload,
    sequence: u64,
    run_start: Instant,
    scheduled: Instant,
) -> Sample {
    let actual_start = Instant::now();
    let dispatch_lag = actual_start.saturating_duration_since(scheduled);
    let scheduled_offset = scheduled.saturating_duration_since(run_start);
    let mut status = None;
    let mut error = None;
    let request = build_request(&client, &endpoint, workload, sequence)
        .header("x-om-d5-arrival", sequence.to_string());
    match request.send().await {
        Ok(response) => {
            status = Some(response.status().as_u16());
            if !response.status().is_success() {
                error = Some(format!("HTTP {}", response.status()));
            }
            if let Err(body_error) = response.bytes().await {
                error = Some(format!("response body: {body_error}"));
            }
        }
        Err(request_error) => error = Some(format!("request: {request_error}")),
    }
    Sample {
        sequence,
        scheduled_offset_ns: scheduled_offset.as_nanos() as u64,
        dispatch_lag_ns: dispatch_lag.as_nanos() as u64,
        response_latency_from_schedule_ns: Instant::now()
            .saturating_duration_since(scheduled)
            .as_nanos() as u64,
        status,
        error,
    }
}

fn collect(
    joined: Result<Sample, tokio::task::JoinError>,
    histogram: &mut Histogram<u64>,
    samples: &mut Vec<Sample>,
) {
    if let Ok(sample) = joined {
        if sample.error.is_none() {
            let _ = histogram.record(
                sample
                    .response_latency_from_schedule_ns
                    .min(HISTOGRAM_MAX_NS),
            );
        }
        samples.push(sample);
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 7 || args.len() > 8 {
        return Err("usage: d5_loadgen URL WORKLOAD RATE_RPS DURATION_SECS MAX_IN_FLIGHT OUTPUT.json [CA.pem]".into());
    }
    let endpoint = Url::parse(&args[1])?;
    if !matches!(endpoint.scheme(), "http" | "https") {
        return Err("URL scheme must be http or https".into());
    }
    let workload = Workload::parse(&args[2])?;
    let rate_rps: u64 = args[3].parse()?;
    let duration_secs: u64 = args[4].parse()?;
    let max_in_flight: usize = args[5].parse()?;
    if rate_rps == 0 || rate_rps > 1_000_000 || duration_secs == 0 || max_in_flight == 0 {
        return Err("rate must be 1..=1000000, duration and max_in_flight must be positive".into());
    }
    let output_path = &args[6];
    let mut client_builder = Client::builder()
        .pool_max_idle_per_host(max_in_flight)
        .timeout(Duration::from_secs(120));
    if let Some(ca_path) = args.get(7) {
        client_builder =
            client_builder.add_root_certificate(Certificate::from_pem(&fs::read(ca_path)?)?);
    }
    let client = client_builder.build()?;

    let mut histogram = Histogram::<u64>::new_with_max(HISTOGRAM_MAX_NS, 3)?;
    let mut samples = Vec::new();
    let mut tasks = JoinSet::new();
    let start = Instant::now();
    let end = start + Duration::from_secs(duration_secs);
    let period_ns = 1_000_000_000u64 / rate_rps;
    let mut offered = 0u64;
    let mut started = 0u64;
    let mut dropped = 0u64;
    let mut late = 0u64;
    let mut next_sequence = 0u64;
    let mut peak_in_flight = 0usize;

    while arrival_at(start, period_ns, next_sequence) < end {
        let scheduled = arrival_at(start, period_ns, next_sequence);
        tokio::select! {
            biased;
            _ = sleep_until(TokioInstant::from_std(scheduled)) => {
                offered += 1;
                if Instant::now().saturating_duration_since(scheduled) > Duration::from_millis(1) {
                    late += 1;
                }
                if tasks.len() >= max_in_flight {
                    dropped += 1;
                } else {
                    let sequence = REQUEST_ID.fetch_add(1, Ordering::Relaxed);
                    let client = client.clone();
                    let endpoint = endpoint.clone();
                    tasks.spawn(issue(client, endpoint, workload, sequence, start, scheduled));
                    started += 1;
                    peak_in_flight = peak_in_flight.max(tasks.len());
                }
                next_sequence += 1;
            }
            Some(joined) = tasks.join_next(), if !tasks.is_empty() => {
                collect(joined, &mut histogram, &mut samples);
            }
        }
    }
    while let Some(joined) = tasks.join_next().await {
        collect(joined, &mut histogram, &mut samples);
    }

    let completed = samples
        .iter()
        .filter(|sample| sample.error.is_none())
        .count() as u64;
    let errors = samples.len() as u64 - completed;
    let hdr_percentiles = [0.50, 0.90, 0.95, 0.99, 0.999]
        .into_iter()
        .map(|percentile| Percentile {
            percentile,
            value_ns: histogram.value_at_quantile(percentile),
        })
        .collect();
    let distribution = (0..=10_000)
        .step_by(10)
        .map(|value| {
            let percentile = value as f64 / 10_000.0;
            Percentile {
                percentile,
                value_ns: histogram.value_at_quantile(percentile),
            }
        })
        .collect();
    let kernel = command_output("uname", &["-r"]);
    let platform_scope = if kernel.contains("microsoft") {
        "WSL2 development-only; not native Linux decision evidence"
    } else {
        "Linux run; qualify host and pinning before decision use"
    };
    let report = Report {
        classification: "measured",
        platform_scope,
        date_utc: command_output("date", &["-u", "+%Y-%m-%dT%H:%M:%SZ"]),
        host: command_output("hostname", &[]),
        rustc_version: command_output("rustc", &["--version"]),
        cargo_version: command_output("cargo", &["--version"]),
        reqwest_version: "0.12.28",
        hdrhistogram_version: "7.5.4",
        endpoint: endpoint.to_string(),
        workload: workload.name(),
        offered_rate_rps: rate_rps,
        planned_duration_seconds: duration_secs,
        max_in_flight,
        tls: endpoint.scheme() == "https",
        offered_arrivals: offered,
        started_requests: started,
        peak_in_flight_observed: peak_in_flight,
        completed_requests: completed,
        dropped_at_concurrency_cap: dropped,
        late_dispatches_over_1ms: late,
        http_or_transport_errors: errors,
        hdrhistogram_significant_digits: 3,
        hdrhistogram_total_count: histogram.len(),
        hdrhistogram_percentiles: hdr_percentiles,
        hdrhistogram_percentile_distribution: distribution,
        client_process_peak_rss_bytes: process_peak_rss_bytes(),
        target_cpu_seconds_per_completed_request: None,
        target_resident_memory_bytes: None,
        kernel,
        cpu_model: read_first_line("/proc/cpuinfo", Some("model name")),
        cpu_frequency_mhz_snapshot: read_first_line("/proc/cpuinfo", Some("cpu MHz")),
        allowed_cpu_list: read_first_line("/proc/self/status", Some("Cpus_allowed_list")),
        cpu_governor: read_first_line("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", None),
        cgroup_cpu_max: read_first_line("/sys/fs/cgroup/cpu.max", None),
        cgroup_memory_max: read_first_line("/sys/fs/cgroup/memory.max", None),
        pinning: "not pinned by harness; use taskset/cgroup cpuset and record IRQ policy for decision-grade runs",
        exact_command: args.join(" "),
        raw_samples: samples,
    };
    fs::write(output_path, serde_json::to_vec_pretty(&report)?)?;
    println!(
        "offered={offered} started={started} completed={completed} dropped={dropped} errors={errors} p50_ns={} p99_ns={} p999_ns={} output={output_path}",
        histogram.value_at_quantile(0.50),
        histogram.value_at_quantile(0.99),
        histogram.value_at_quantile(0.999)
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workload_paths_and_methods_are_stable() {
        let client = Client::new();
        let endpoint = Url::parse("http://127.0.0.1:8081").unwrap();

        let sse = build_request(&client, &endpoint, Workload::Sse500, 4)
            .build()
            .unwrap();
        assert_eq!(sse.method(), Method::POST);
        assert_eq!(sse.url().path(), "/v1/chat/completions");

        let mcp = build_request(&client, &endpoint, Workload::Mcp, 5)
            .build()
            .unwrap();
        assert_eq!(mcp.method(), Method::POST);
        assert_eq!(mcp.url().path(), "/mcp");

        let fanout = build_request(&client, &endpoint, Workload::Fanout, 6)
            .build()
            .unwrap();
        assert_eq!(fanout.method(), Method::GET);
        assert_eq!(fanout.url().path(), "/fanout");
        assert_eq!(fanout.url().query(), Some("n=16"));
    }

    #[test]
    fn open_loop_arrivals_keep_their_fixed_schedule() {
        let start = Instant::now();
        let period = 250_000_000;
        let arrivals: Vec<_> = (0..5)
            .map(|index| arrival_at(start, period, index))
            .collect();
        assert_eq!(arrivals[0], start);
        assert_eq!(
            arrivals[1].duration_since(arrivals[0]).as_nanos(),
            period as u128
        );
        assert_eq!(
            arrivals[4].duration_since(arrivals[0]).as_nanos(),
            (period * 4) as u128
        );
    }
}
