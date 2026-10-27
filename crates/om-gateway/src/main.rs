use std::{
    collections::HashMap, convert::Infallible, error::Error, net::SocketAddr, path::PathBuf,
    time::Instant,
};

use bytes::Bytes;
use http_body_util::{combinators::UnsyncBoxBody, BodyExt, Full, Limited};
use hyper::{
    body::Incoming,
    header::{HeaderName, HeaderValue, CONTENT_TYPE},
    service::service_fn,
    Method, Request, Response, StatusCode, Uri,
};
use hyper_util::{
    client::legacy::{connect::HttpConnector, Client},
    rt::{TokioExecutor, TokioIo},
};
use om_core::{new_request_id, valid_request_id, Address, ErrorEnvelope};
use serde::Deserialize;
use serde_json::{json, Value};
use tokio::{
    net::TcpListener,
    task::JoinSet,
    time::{timeout, Duration},
};

const MAX_REQUEST_BYTES: usize = 1024 * 1024;
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);
type BoxError = Box<dyn Error + Send + Sync>;
type GatewayBody = UnsyncBoxBody<Bytes, BoxError>;
type UpstreamClient = Client<HttpConnector, Full<Bytes>>;

#[derive(Clone, Deserialize)]
struct RawConfig {
    listen: String,
    routes: Vec<RawRoute>,
}

#[derive(Clone, Deserialize)]
struct RawRoute {
    model: String,
    upstream: String,
}

#[derive(Clone)]
struct AppState {
    client: UpstreamClient,
    routes: HashMap<Address, Uri>,
}

fn full_body(value: impl Into<Bytes>) -> GatewayBody {
    Full::new(value.into())
        .map_err(|never: Infallible| match never {})
        .boxed_unsync()
}

fn response(
    status: StatusCode,
    request_id: &str,
    content_type: &'static str,
    body: Value,
) -> Response<GatewayBody> {
    let mut result = Response::new(full_body(Bytes::from(body.to_string())));
    *result.status_mut() = status;
    result
        .headers_mut()
        .insert(CONTENT_TYPE, HeaderValue::from_static(content_type));
    if let Ok(value) = HeaderValue::from_str(request_id) {
        result.headers_mut().insert("x-request-id", value);
    }
    result
}

fn api_error(
    status: StatusCode,
    request_id: &str,
    code: &str,
    message: &str,
) -> Response<GatewayBody> {
    let envelope = ErrorEnvelope::new(code, message);
    response(
        status,
        request_id,
        "application/json",
        serde_json::to_value(envelope).expect("error envelope serializes"),
    )
}

fn load_config() -> Result<(SocketAddr, HashMap<Address, Uri>), BoxError> {
    let config_path = std::env::var_os("OM_GATEWAY_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("crates/om-gateway/config/routes.local.json"));
    let config_bytes = std::fs::read(&config_path)?;
    let raw: RawConfig = serde_json::from_slice(&config_bytes)?;
    let listen = std::env::var("OM_GATEWAY_LISTEN").unwrap_or(raw.listen);
    let listen: SocketAddr = listen.parse()?;
    let mut routes = HashMap::new();
    for route in raw.routes {
        let address = Address::parse(&route.model)?;
        let upstream: Uri = route.upstream.parse()?;
        if upstream.scheme_str() != Some("http")
            || upstream.authority().is_none()
            || !matches!(upstream.path(), "" | "/")
        {
            return Err(format!("upstream for {} must be an HTTP origin", route.model).into());
        }
        if routes.insert(address, upstream).is_some() {
            return Err(format!("duplicate model route: {}", route.model).into());
        }
    }
    if routes.is_empty() {
        return Err("route configuration must contain at least one route".into());
    }
    Ok((listen, routes))
}

fn request_id(request: &Request<Incoming>) -> String {
    request
        .headers()
        .get("x-request-id")
        .and_then(|value| value.to_str().ok())
        .filter(|value| valid_request_id(value))
        .map(str::to_owned)
        .unwrap_or_else(new_request_id)
}

fn write_log(
    request_id: &str,
    method: &Method,
    path: &str,
    status: StatusCode,
    upstream: Option<&Uri>,
    elapsed_ms: u128,
) {
    println!(
        "{}",
        json!({
            "level": "info",
            "service": "om-gateway",
            "event": "request_complete",
            "request_id": request_id,
            "method": method.as_str(),
            "path": path,
            "status": status.as_u16(),
            "upstream": upstream.map(Uri::to_string),
            "elapsed_ms": elapsed_ms,
        })
    );
}

fn is_hop_header(name: &HeaderName) -> bool {
    matches!(
        name.as_str(),
        "connection"
            | "keep-alive"
            | "proxy-authenticate"
            | "proxy-authorization"
            | "te"
            | "trailer"
            | "transfer-encoding"
            | "upgrade"
            | "host"
    )
}

fn upstream_uri(base: &Uri, incoming: &Uri) -> Result<Uri, BoxError> {
    let authority = base.authority().ok_or("upstream URI has no authority")?;
    let path_and_query = incoming
        .path_and_query()
        .map(|value| value.as_str())
        .unwrap_or("/");
    Ok(format!("http://{authority}{path_and_query}").parse()?)
}

async fn ready(state: &AppState) -> bool {
    let Some(upstream) = state.routes.values().next() else {
        return false;
    };
    let uri = format!(
        "{}://{}/healthz",
        upstream.scheme_str().unwrap_or("http"),
        upstream
            .authority()
            .map(|value| value.as_str())
            .unwrap_or_default()
    )
    .parse::<Uri>();
    let Ok(uri) = uri else { return false };
    let request = Request::get(uri).body(Full::new(Bytes::new()));
    let Ok(request) = request else {
        return false;
    };
    matches!(
        timeout(Duration::from_secs(1), state.client.request(request)).await,
        Ok(Ok(response)) if response.status().is_success()
    )
}

async fn handle(request: Request<Incoming>, state: AppState) -> Response<GatewayBody> {
    let started = Instant::now();
    let id = request_id(&request);
    let method = request.method().clone();
    let path = request.uri().path().to_owned();
    let mut upstream_for_log = None;

    let result = match (method.clone(), path.as_str()) {
        (Method::GET, "/healthz") => response(
            StatusCode::OK,
            &id,
            "application/json",
            json!({"status":"ok","service":"om-gateway"}),
        ),
        (Method::GET, "/readyz") => {
            if ready(&state).await {
                response(
                    StatusCode::OK,
                    &id,
                    "application/json",
                    json!({"status":"ready","service":"om-gateway"}),
                )
            } else {
                api_error(
                    StatusCode::SERVICE_UNAVAILABLE,
                    &id,
                    "OS-0300",
                    "no configured upstream is healthy",
                )
            }
        }
        (Method::POST, "/v1/chat/completions") => {
            let (parts, body) = request.into_parts();
            let collected = Limited::new(body, MAX_REQUEST_BYTES).collect().await;
            let body = match collected {
                Ok(body) => body.to_bytes(),
                Err(_) => {
                    return api_error(
                        StatusCode::PAYLOAD_TOO_LARGE,
                        &id,
                        "OS-0001",
                        "request body exceeds the 1 MiB limit",
                    );
                }
            };
            let payload: Value = match serde_json::from_slice(&body) {
                Ok(value) => value,
                Err(_) => {
                    return api_error(
                        StatusCode::BAD_REQUEST,
                        &id,
                        "OS-0001",
                        "request body must be a JSON object",
                    );
                }
            };
            let Some(model) = payload.get("model").and_then(Value::as_str) else {
                return api_error(
                    StatusCode::BAD_REQUEST,
                    &id,
                    "OS-0001",
                    "request must name a model address",
                );
            };
            let address = match Address::parse(model) {
                Ok(address) => address,
                Err(_) => {
                    return api_error(
                        StatusCode::BAD_REQUEST,
                        &id,
                        "OS-0001",
                        "model must use om://authority/path form",
                    );
                }
            };
            let Some(upstream) = state.routes.get(&address).cloned() else {
                return api_error(
                    StatusCode::SERVICE_UNAVAILABLE,
                    &id,
                    "OS-0300",
                    "no configured route is available for this model",
                );
            };
            upstream_for_log = Some(upstream.clone());
            let uri = match upstream_uri(&upstream, &parts.uri) {
                Ok(uri) => uri,
                Err(_) => {
                    return api_error(
                        StatusCode::BAD_GATEWAY,
                        &id,
                        "OS-0302",
                        "upstream request could not be constructed",
                    );
                }
            };
            let mut builder = Request::builder().method(parts.method).uri(uri);
            for (name, value) in &parts.headers {
                if !is_hop_header(name) && name.as_str() != "x-request-id" {
                    builder = builder.header(name, value);
                }
            }
            builder = builder.header("x-request-id", &id);
            let outbound = match builder.body(Full::new(body)) {
                Ok(request) => request,
                Err(_) => {
                    return api_error(
                        StatusCode::BAD_REQUEST,
                        &id,
                        "OS-0001",
                        "request headers are invalid",
                    );
                }
            };
            match state.client.request(outbound).await {
                Ok(upstream_response) => {
                    let (parts, body) = upstream_response.into_parts();
                    let mut builder = Response::builder().status(parts.status);
                    for (name, value) in &parts.headers {
                        if !is_hop_header(name) && name.as_str() != "x-request-id" {
                            builder = builder.header(name, value);
                        }
                    }
                    let response_body = body
                        .map_err(|error| Box::new(error) as BoxError)
                        .boxed_unsync();
                    match builder.header("x-request-id", &id).body(response_body) {
                        Ok(response) => response,
                        Err(_) => api_error(
                            StatusCode::BAD_GATEWAY,
                            &id,
                            "OS-0302",
                            "upstream response headers are invalid",
                        ),
                    }
                }
                Err(_) => api_error(
                    StatusCode::BAD_GATEWAY,
                    &id,
                    "OS-0302",
                    "upstream request failed",
                ),
            }
        }
        _ => api_error(
            StatusCode::NOT_FOUND,
            &id,
            "OS-0001",
            "endpoint is not available",
        ),
    };

    write_log(
        &id,
        &method,
        &path,
        result.status(),
        upstream_for_log.as_ref(),
        started.elapsed().as_millis(),
    );
    result
}

async fn shutdown_signal() {
    #[cfg(unix)]
    {
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .expect("install SIGTERM handler");
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {},
            _ = terminate.recv() => {},
        }
    }
    #[cfg(not(unix))]
    {
        let _ = tokio::signal::ctrl_c().await;
    }
}

#[tokio::main]
async fn main() -> Result<(), BoxError> {
    let (listen, routes) = load_config()?;
    let listener = TcpListener::bind(listen).await?;
    let client = Client::builder(TokioExecutor::new())
        .pool_max_idle_per_host(32)
        .build_http();
    let state = AppState { client, routes };
    let mut connections = JoinSet::new();
    let shutdown = shutdown_signal();
    tokio::pin!(shutdown);
    println!(
        "{}",
        json!({"level":"info","service":"om-gateway","event":"listening","address":listen})
    );

    loop {
        tokio::select! {
            _ = &mut shutdown => break,
            joined = connections.join_next(), if !connections.is_empty() => {
                if let Some(Err(error)) = joined {
                    eprintln!("{{\"level\":\"error\",\"service\":\"om-gateway\",\"event\":\"connection_task_failed\",\"error\":{}}}", json!(error.to_string()));
                }
            }
            accepted = listener.accept() => {
                let (stream, _) = accepted?;
                let io = TokioIo::new(stream);
                let service_state = state.clone();
                connections.spawn(async move {
                    let service = service_fn(move |request| {
                        let state = service_state.clone();
                        async move { Ok::<_, Infallible>(handle(request, state).await) }
                    });
                    let builder = hyper::server::conn::http1::Builder::new();
                    if let Err(error) = builder.serve_connection(io, service).await {
                        eprintln!("{{\"level\":\"warn\",\"service\":\"om-gateway\",\"event\":\"connection_closed\",\"error\":{}}}", json!(error.to_string()));
                    }
                });
            }
        }
    }

    let drained = timeout(SHUTDOWN_GRACE, async {
        while connections.join_next().await.is_some() {}
    })
    .await;
    if drained.is_err() {
        connections.abort_all();
        while connections.join_next().await.is_some() {}
    }
    println!(
        "{}",
        json!({"level":"info","service":"om-gateway","event":"shutdown_complete"})
    );
    Ok(())
}
