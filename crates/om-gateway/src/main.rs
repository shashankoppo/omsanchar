use std::{
    collections::HashMap,
    convert::Infallible,
    error::Error,
    future::Future,
    io,
    net::SocketAddr,
    path::PathBuf,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
    time::{Instant, SystemTime},
};

use bytes::Bytes;
use futures_util::stream;
use http_body_util::{combinators::UnsyncBoxBody, BodyExt, Full, Limited, StreamBody};
use hyper::{
    body::{Body, Incoming},
    header::{HeaderName, HeaderValue, CONTENT_TYPE},
    service::service_fn,
    Method, Request, Response, StatusCode, Uri,
};
use hyper_util::{
    client::legacy::{connect::HttpConnector, Client},
    rt::{TokioExecutor, TokioIo},
};
use om_core::{new_request_id, valid_request_id, Address, ErrorEnvelope};
use om_token::{Grant, RequestScope, TokenAuthority, TokenError};
use serde::Deserialize;
use serde_json::{json, Value};
use tokio::{
    io::{AsyncRead, AsyncWrite, ReadBuf},
    net::TcpListener,
    sync::{watch, OwnedSemaphorePermit, Semaphore},
    task::JoinSet,
    time::{timeout, Duration},
};

const MAX_REQUEST_BYTES: usize = 1024 * 1024;
const MAX_HEADER_BYTES: usize = 16 * 1024;
const MAX_STREAM_FRAME_BYTES: usize = 64 * 1024;
const MAX_CONCURRENT_STREAMS: usize = 128;
const UPSTREAM_CONNECT_TIMEOUT: Duration = Duration::from_secs(3);
const UPSTREAM_RESPONSE_TIMEOUT: Duration = Duration::from_secs(10);
const UPSTREAM_READ_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);
type BoxError = Box<dyn Error + Send + Sync>;
type GatewayBody = UnsyncBoxBody<Bytes, BoxError>;
type UpstreamClient = Client<HttpConnector, Full<Bytes>>;

struct HeaderLimitIo<T> {
    inner: T,
    header_bytes: Vec<u8>,
    header_complete: bool,
}

impl<T> HeaderLimitIo<T> {
    fn new(inner: T) -> Self {
        Self {
            inner,
            header_bytes: Vec::with_capacity(MAX_HEADER_BYTES),
            header_complete: false,
        }
    }
}

impl<T: AsyncRead + Unpin> AsyncRead for HeaderLimitIo<T> {
    fn poll_read(
        mut self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        let start = buffer.filled().len();
        match Pin::new(&mut self.inner).poll_read(context, buffer) {
            Poll::Ready(Ok(())) if !self.header_complete => {
                let read = &buffer.filled()[start..];
                self.header_bytes.extend_from_slice(read);
                if let Some(end) = self
                    .header_bytes
                    .windows(4)
                    .position(|bytes| bytes == b"\r\n\r\n")
                {
                    self.header_complete = true;
                    if end + 4 > MAX_HEADER_BYTES {
                        return Poll::Ready(Err(io::Error::new(
                            io::ErrorKind::InvalidData,
                            "request headers exceed the 16 KiB limit",
                        )));
                    }
                    self.header_bytes.clear();
                } else if self.header_bytes.len() >= MAX_HEADER_BYTES {
                    return Poll::Ready(Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "request headers exceed the 16 KiB limit",
                    )));
                }
                Poll::Ready(Ok(()))
            }
            result => result,
        }
    }
}

impl<T: AsyncWrite + Unpin> AsyncWrite for HeaderLimitIo<T> {
    fn poll_write(
        mut self: Pin<&mut Self>,
        context: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<io::Result<usize>> {
        Pin::new(&mut self.inner).poll_write(context, bytes)
    }

    fn poll_flush(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.inner).poll_flush(context)
    }

    fn poll_shutdown(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.inner).poll_shutdown(context)
    }
}

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
    streams: Arc<Semaphore>,
    tokens: Arc<TokenAuthority>,
    authenticator: Arc<dyn RequestAuthenticator>,
    admin_token: Arc<str>,
}

trait RequestAuthenticator: Send + Sync {
    fn verify(&self, token: &str, scope: &RequestScope) -> Result<(), TokenError>;
}

impl RequestAuthenticator for TokenAuthority {
    fn verify(&self, token: &str, scope: &RequestScope) -> Result<(), TokenError> {
        TokenAuthority::verify(self, token, scope)
    }
}

#[derive(Deserialize)]
struct IssueTokenRequest {
    tenant: String,
    model: String,
    budget_microcredits: i64,
    max_output_tokens: i64,
    expires_in_seconds: u64,
}

#[derive(Deserialize)]
struct AttenuateTokenRequest {
    token: String,
    tenant: String,
    model: String,
    budget_microcredits: i64,
    max_output_tokens: i64,
    expires_at_unix_seconds: u64,
}

#[derive(Deserialize)]
struct RevokeTokenRequest {
    token: String,
}

fn bounded_response_body(body: Incoming, permit: OwnedSemaphorePermit) -> GatewayBody {
    bounded_response_body_with_limits(body, permit, UPSTREAM_READ_TIMEOUT, MAX_STREAM_FRAME_BYTES)
}

fn bounded_response_body_with_limits<B>(
    body: B,
    permit: OwnedSemaphorePermit,
    read_timeout: Duration,
    max_frame_bytes: usize,
) -> GatewayBody
where
    B: Body<Data = Bytes> + Unpin + Send + 'static,
    B::Error: Error + Send + Sync + 'static,
{
    let stream = stream::try_unfold((body, permit), move |(mut body, permit)| async move {
        match timeout(read_timeout, body.frame()).await {
            Err(_) => Err(Box::new(io::Error::new(
                io::ErrorKind::TimedOut,
                "upstream response stalled beyond the read timeout",
            )) as BoxError),
            Ok(None) => Ok(None),
            Ok(Some(Err(error))) => Err(Box::new(error) as BoxError),
            Ok(Some(Ok(frame))) => {
                if frame
                    .data_ref()
                    .is_some_and(|data| data.len() > max_frame_bytes)
                {
                    return Err(Box::new(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "upstream frame exceeds the per-stream buffer cap",
                    )) as BoxError);
                }
                Ok(Some((frame, (body, permit))))
            }
        }
    });
    StreamBody::new(stream).boxed_unsync()
}

async fn limited_request_body<B>(body: B, max_bytes: usize) -> Result<Bytes, ()>
where
    B: Body<Data = Bytes> + Unpin,
    B::Error: Error + Send + Sync + 'static,
{
    Limited::new(body, max_bytes)
        .collect()
        .await
        .map(|collected| collected.to_bytes())
        .map_err(|_| ())
}

#[derive(Debug, PartialEq, Eq)]
enum UpstreamTimeout {
    Failed,
    TimedOut,
}

async fn upstream_request<F, T, E>(request: F) -> Result<T, UpstreamTimeout>
where
    F: Future<Output = Result<T, E>>,
{
    upstream_request_with_timeout(request, UPSTREAM_RESPONSE_TIMEOUT).await
}

async fn upstream_request_with_timeout<F, T, E>(
    request: F,
    response_timeout: Duration,
) -> Result<T, UpstreamTimeout>
where
    F: Future<Output = Result<T, E>>,
{
    match timeout(response_timeout, request).await {
        Ok(Ok(response)) => Ok(response),
        Ok(Err(_)) => Err(UpstreamTimeout::Failed),
        Err(_) => Err(UpstreamTimeout::TimedOut),
    }
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

fn text_response(
    status: StatusCode,
    request_id: &str,
    content_type: &'static str,
    body: String,
) -> Response<GatewayBody> {
    let mut result = Response::new(full_body(Bytes::from(body)));
    *result.status_mut() = status;
    result
        .headers_mut()
        .insert(CONTENT_TYPE, HeaderValue::from_static(content_type));
    if let Ok(value) = HeaderValue::from_str(request_id) {
        result.headers_mut().insert("x-request-id", value);
    }
    result
}

fn constant_time_equal(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0u8, |difference, (left, right)| difference | (left ^ right))
        == 0
}

fn is_admin_request(request: &Request<Incoming>, state: &AppState) -> bool {
    request
        .headers()
        .get("x-om-admin-token")
        .and_then(|value| value.to_str().ok())
        .is_some_and(|provided| {
            constant_time_equal(provided.as_bytes(), state.admin_token.as_bytes())
        })
}

fn bearer_token(headers: &hyper::HeaderMap) -> Option<&str> {
    let value = headers.get(hyper::header::AUTHORIZATION)?.to_str().ok()?;
    value
        .strip_prefix("Bearer ")
        .filter(|token| !token.is_empty())
}

fn token_error_response(request_id: &str, error: TokenError) -> Response<GatewayBody> {
    match error {
        TokenError::InvalidInput(message) => {
            api_error(StatusCode::BAD_REQUEST, request_id, "OS-0101", message)
        }
        TokenError::InvalidToken | TokenError::Revoked => api_error(
            StatusCode::UNAUTHORIZED,
            request_id,
            "OS-0100",
            "capability token is invalid, expired, or revoked",
        ),
        TokenError::Unauthorized => api_error(
            StatusCode::FORBIDDEN,
            request_id,
            "OS-0101",
            "capability token does not authorize this request",
        ),
        TokenError::RevocationCapacity => api_error(
            StatusCode::SERVICE_UNAVAILABLE,
            request_id,
            "OS-0503",
            "bounded token revocation capacity is full",
        ),
        TokenError::Internal => api_error(
            StatusCode::INTERNAL_SERVER_ERROR,
            request_id,
            "OS-0600",
            "capability token operation failed",
        ),
    }
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
        (Method::GET, "/metrics") => text_response(
            StatusCode::OK,
            &id,
            "text/plain; version=0.0.4",
            format!(
                "om_token_cache_entries {}\nom_token_cache_hits_total {}\nom_token_cache_evictions_total {}\nom_token_revocation_entries {}\n",
                state.tokens.cache_entries(),
                state.tokens.cache_hits(),
                state.tokens.cache_evictions(),
                state.tokens.revocation_entries(),
            ),
        ),
        (Method::POST, "/v1/control/tokens") => {
            if !is_admin_request(&request, &state) {
                return api_error(
                    StatusCode::UNAUTHORIZED,
                    &id,
                    "OS-0100",
                    "control-plane administrator authentication is required",
                );
            }
            let (_, body) = request.into_parts();
            let body = match limited_request_body(body, MAX_REQUEST_BYTES).await {
                Ok(body) => body,
                Err(()) => {
                    return api_error(
                        StatusCode::PAYLOAD_TOO_LARGE,
                        &id,
                        "OS-0001",
                        "request body exceeds the 1 MiB limit",
                    );
                }
            };
            let issue: IssueTokenRequest = match serde_json::from_slice(&body) {
                Ok(issue) => issue,
                Err(_) => {
                    return api_error(
                        StatusCode::BAD_REQUEST,
                        &id,
                        "OS-0001",
                        "token grant body is invalid",
                    );
                }
            };
            if !(1..=86_400).contains(&issue.expires_in_seconds) {
                return api_error(
                    StatusCode::BAD_REQUEST,
                    &id,
                    "OS-0101",
                    "expires_in_seconds must be between 1 and 86400",
                );
            }
            let Some(expires_at_unix_seconds) = SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .ok()
                .and_then(|now| now.as_secs().checked_add(issue.expires_in_seconds))
            else {
                return api_error(
                    StatusCode::BAD_REQUEST,
                    &id,
                    "OS-0101",
                    "token expiry is out of range",
                );
            };
            let grant = Grant {
                tenant: issue.tenant,
                model: issue.model,
                budget_microcredits: issue.budget_microcredits,
                max_output_tokens: issue.max_output_tokens,
                expires_at_unix_seconds,
            };
            match state.tokens.mint(&grant) {
                Ok(token) => response(
                    StatusCode::CREATED,
                    &id,
                    "application/json",
                    json!({"token":token,"token_type":"Bearer","expires_at_unix_seconds":expires_at_unix_seconds}),
                ),
                Err(error) => token_error_response(&id, error),
            }
        }
        (Method::POST, "/v1/control/tokens/attenuate") => {
            if !is_admin_request(&request, &state) {
                return api_error(
                    StatusCode::UNAUTHORIZED,
                    &id,
                    "OS-0100",
                    "control-plane administrator authentication is required",
                );
            }
            let (_, body) = request.into_parts();
            let body = match limited_request_body(body, MAX_REQUEST_BYTES).await {
                Ok(body) => body,
                Err(()) => {
                    return api_error(
                        StatusCode::PAYLOAD_TOO_LARGE,
                        &id,
                        "OS-0001",
                        "request body exceeds the 1 MiB limit",
                    );
                }
            };
            let attenuation: AttenuateTokenRequest = match serde_json::from_slice(&body) {
                Ok(attenuation) => attenuation,
                Err(_) => {
                    return api_error(
                        StatusCode::BAD_REQUEST,
                        &id,
                        "OS-0001",
                        "token attenuation body is invalid",
                    );
                }
            };
            let grant = Grant {
                tenant: attenuation.tenant,
                model: attenuation.model,
                budget_microcredits: attenuation.budget_microcredits,
                max_output_tokens: attenuation.max_output_tokens,
                expires_at_unix_seconds: attenuation.expires_at_unix_seconds,
            };
            match state.tokens.attenuate(&attenuation.token, &grant) {
                Ok(token) => response(
                    StatusCode::CREATED,
                    &id,
                    "application/json",
                    json!({"token":token,"token_type":"Bearer","expires_at_unix_seconds":grant.expires_at_unix_seconds}),
                ),
                Err(error) => token_error_response(&id, error),
            }
        }
        (Method::POST, "/v1/control/tokens/revoke") => {
            if !is_admin_request(&request, &state) {
                return api_error(
                    StatusCode::UNAUTHORIZED,
                    &id,
                    "OS-0100",
                    "control-plane administrator authentication is required",
                );
            }
            let (_, body) = request.into_parts();
            let body = match limited_request_body(body, MAX_REQUEST_BYTES).await {
                Ok(body) => body,
                Err(()) => {
                    return api_error(
                        StatusCode::PAYLOAD_TOO_LARGE,
                        &id,
                        "OS-0001",
                        "request body exceeds the 1 MiB limit",
                    );
                }
            };
            let revoke: RevokeTokenRequest = match serde_json::from_slice(&body) {
                Ok(revoke) => revoke,
                Err(_) => {
                    return api_error(
                        StatusCode::BAD_REQUEST,
                        &id,
                        "OS-0001",
                        "token revocation body is invalid",
                    );
                }
            };
            match state.tokens.revoke(&revoke.token) {
                Ok(()) => response(
                    StatusCode::OK,
                    &id,
                    "application/json",
                    json!({"revoked":true}),
                ),
                Err(error) => token_error_response(&id, error),
            }
        }
        (Method::POST, "/v1/chat/completions") => {
            let (parts, body) = request.into_parts();
            let body = match limited_request_body(body, MAX_REQUEST_BYTES).await {
                Ok(body) => body,
                Err(()) => {
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
            let Some(token) = bearer_token(&parts.headers) else {
                return api_error(
                    StatusCode::UNAUTHORIZED,
                    &id,
                    "OS-0100",
                    "a Biscuit bearer capability is required",
                );
            };
            let Some(tenant) = parts
                .headers
                .get("x-om-tenant")
                .and_then(|value| value.to_str().ok())
            else {
                return api_error(
                    StatusCode::BAD_REQUEST,
                    &id,
                    "OS-0001",
                    "x-om-tenant is required",
                );
            };
            let Some(requested_budget_microcredits) = parts
                .headers
                .get("x-om-budget-microcredits")
                .and_then(|value| value.to_str().ok())
                .and_then(|value| value.parse::<i64>().ok())
            else {
                return api_error(
                    StatusCode::BAD_REQUEST,
                    &id,
                    "OS-0001",
                    "x-om-budget-microcredits must be an integer",
                );
            };
            let requested_output_tokens = payload
                .get("max_tokens")
                .and_then(Value::as_i64)
                .unwrap_or(0);
            let scope = RequestScope {
                tenant: tenant.to_owned(),
                model: model.to_owned(),
                requested_budget_microcredits,
                requested_output_tokens,
            };
            if let Err(error) = state.authenticator.verify(token, &scope) {
                return token_error_response(&id, error);
            }
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
            let stream_permit = match state.streams.clone().try_acquire_owned() {
                Ok(permit) => permit,
                Err(_) => {
                    return api_error(
                        StatusCode::SERVICE_UNAVAILABLE,
                        &id,
                        "OS-0300",
                        "maximum concurrent stream capacity reached",
                    );
                }
            };
            match upstream_request(state.client.request(outbound)).await {
                Ok(upstream_response) => {
                    let (parts, body) = upstream_response.into_parts();
                    let mut builder = Response::builder().status(parts.status);
                    for (name, value) in &parts.headers {
                        if !is_hop_header(name) && name.as_str() != "x-request-id" {
                            builder = builder.header(name, value);
                        }
                    }
                    let response_body = bounded_response_body(body, stream_permit);
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
                Err(UpstreamTimeout::TimedOut) => api_error(
                    StatusCode::GATEWAY_TIMEOUT,
                    &id,
                    "OS-0302",
                    "upstream response timed out",
                ),
                Err(UpstreamTimeout::Failed) => api_error(
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

async fn serve<F>(listener: TcpListener, state: AppState, shutdown: F) -> Result<(), BoxError>
where
    F: Future<Output = ()>,
{
    let mut connections = JoinSet::new();
    let (shutdown_tx, _) = watch::channel(false);
    tokio::pin!(shutdown);

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
                let io = TokioIo::new(HeaderLimitIo::new(stream));
                let service_state = state.clone();
                let mut connection_shutdown = shutdown_tx.subscribe();
                connections.spawn(async move {
                    let service = service_fn(move |request| {
                        let state = service_state.clone();
                        async move { Ok::<_, Infallible>(handle(request, state).await) }
                    });
                    let mut builder = hyper::server::conn::http1::Builder::new();
                    builder.max_buf_size(MAX_HEADER_BYTES);
                    let connection = builder.serve_connection(io, service);
                    tokio::pin!(connection);
                    let result = tokio::select! {
                        result = &mut connection => result,
                        changed = connection_shutdown.changed() => {
                            if changed.is_ok() && *connection_shutdown.borrow() {
                                connection.as_mut().graceful_shutdown();
                            }
                            connection.await
                        }
                    };
                    if let Err(error) = result {
                        eprintln!("{{\"level\":\"warn\",\"service\":\"om-gateway\",\"event\":\"connection_closed\",\"error\":{}}}", json!(error.to_string()));
                    }
                });
            }
        }
    }

    let _ = shutdown_tx.send(true);
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

#[tokio::main]
async fn main() -> Result<(), BoxError> {
    let (listen, routes) = load_config()?;
    let listener = TcpListener::bind(listen).await?;
    let mut connector = HttpConnector::new();
    connector.set_connect_timeout(Some(UPSTREAM_CONNECT_TIMEOUT));
    let client = Client::builder(TokioExecutor::new())
        .http1_max_buf_size(MAX_STREAM_FRAME_BYTES)
        .pool_max_idle_per_host(32)
        .build(connector);
    let root_secret =
        std::env::var("OM_TOKEN_ROOT_SECRET").map_err(|_| "OM_TOKEN_ROOT_SECRET must be set")?;
    let admin_token = std::env::var("OM_ADMIN_TOKEN").map_err(|_| "OM_ADMIN_TOKEN must be set")?;
    if admin_token.len() < 32 {
        return Err("OM_ADMIN_TOKEN must contain at least 32 bytes".into());
    }
    let tokens = Arc::new(
        TokenAuthority::from_secret(root_secret.as_bytes())
            .map_err(|_| "OM_TOKEN_ROOT_SECRET must contain at least 32 bytes")?,
    );
    let authenticator: Arc<dyn RequestAuthenticator> = tokens.clone();
    let state = AppState {
        client,
        routes,
        streams: Arc::new(Semaphore::new(MAX_CONCURRENT_STREAMS)),
        tokens,
        authenticator,
        admin_token: Arc::from(admin_token),
    };
    println!(
        "{}",
        json!({"level":"info","service":"om-gateway","event":"listening","address":listen})
    );
    serve(listener, state, shutdown_signal()).await
}

#[cfg(test)]
mod tests {
    use std::{
        collections::{HashMap, VecDeque},
        io,
        net::SocketAddr,
        pin::Pin,
        sync::{
            atomic::{AtomicUsize, Ordering},
            Arc, Mutex,
        },
        task::{Context, Poll},
        time::{SystemTime, UNIX_EPOCH},
    };

    use bytes::Bytes;
    use futures_util::{stream, StreamExt};
    use http_body_util::{BodyExt, Full, StreamBody};
    use hyper::{
        body::{Body, Frame},
        service::service_fn,
        Request, Response, Uri,
    };
    use hyper_util::rt::{TokioExecutor, TokioIo};
    use om_core::Address;
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::{TcpListener, TcpStream},
        sync::{oneshot, Semaphore},
        task::JoinHandle,
        time::{sleep, timeout, Duration},
    };

    use super::{
        bounded_response_body_with_limits, limited_request_body, serve, AppState, BoxError, Grant,
        RequestAuthenticator, TokenAuthority, UpstreamClient, UpstreamTimeout,
        MAX_CONCURRENT_STREAMS, MAX_HEADER_BYTES, MAX_REQUEST_BYTES, MAX_STREAM_FRAME_BYTES,
        UPSTREAM_CONNECT_TIMEOUT,
    };

    const TEST_TOKEN_SECRET: &[u8] = b"om-sanchar-test-root-secret-32-byte-minimum";
    const TEST_ADMIN_TOKEN: &str = "om-sanchar-test-admin-secret-at-least-32-bytes";

    struct ScriptedBody {
        frames: VecDeque<Bytes>,
        polls: Arc<AtomicUsize>,
        pending: bool,
        on_drop: Option<oneshot::Sender<()>>,
    }

    impl Body for ScriptedBody {
        type Data = Bytes;
        type Error = io::Error;

        fn poll_frame(
            mut self: Pin<&mut Self>,
            _context: &mut Context<'_>,
        ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
            self.polls.fetch_add(1, Ordering::Relaxed);
            if self.pending {
                return Poll::Pending;
            }
            Poll::Ready(self.frames.pop_front().map(|bytes| Ok(Frame::data(bytes))))
        }
    }

    impl Drop for ScriptedBody {
        fn drop(&mut self) {
            if let Some(sender) = self.on_drop.take() {
                let _ = sender.send(());
            }
        }
    }

    struct DropSignal(Option<oneshot::Sender<()>>);

    impl Drop for DropSignal {
        fn drop(&mut self) {
            if let Some(sender) = self.0.take() {
                let _ = sender.send(());
            }
        }
    }

    fn empty_client() -> UpstreamClient {
        hyper_util::client::legacy::Client::builder(TokioExecutor::new()).build_http()
    }

    fn state(routes: HashMap<Address, Uri>) -> AppState {
        let tokens = Arc::new(
            TokenAuthority::from_secret(TEST_TOKEN_SECRET).expect("test root secret is valid"),
        );
        let authenticator: Arc<dyn RequestAuthenticator> = tokens.clone();
        AppState {
            client: empty_client(),
            routes,
            streams: Arc::new(Semaphore::new(MAX_CONCURRENT_STREAMS)),
            tokens,
            authenticator,
            admin_token: Arc::from(TEST_ADMIN_TOKEN),
        }
    }

    async fn spawn_gateway(
        routes: HashMap<Address, Uri>,
    ) -> (
        SocketAddr,
        oneshot::Sender<()>,
        JoinHandle<Result<(), BoxError>>,
    ) {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let (shutdown_sender, shutdown_receiver) = oneshot::channel();
        let task = tokio::spawn(serve(listener, state(routes), async move {
            let _ = shutdown_receiver.await;
        }));
        (address, shutdown_sender, task)
    }

    async fn spawn_finite_upstream(chunks: Vec<Bytes>) -> (Uri, JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let task = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let io = TokioIo::new(stream);
            let service = service_fn(move |_request: Request<hyper::body::Incoming>| {
                let chunks = chunks.clone();
                async move {
                    let body_stream = stream::iter(
                        chunks
                            .into_iter()
                            .map(|bytes| Ok::<_, std::convert::Infallible>(Frame::data(bytes))),
                    )
                    .then(|frame| async move {
                        sleep(Duration::from_millis(40)).await;
                        frame
                    });
                    let body = StreamBody::new(body_stream).boxed_unsync();
                    Ok::<_, std::convert::Infallible>(
                        Response::builder()
                            .header("content-type", "text/event-stream")
                            .body(body)
                            .unwrap(),
                    )
                }
            });
            let _ = hyper::server::conn::http1::Builder::new()
                .serve_connection(io, service)
                .await;
        });
        (format!("http://{address}").parse().unwrap(), task)
    }

    async fn spawn_stalling_upstream() -> (Uri, oneshot::Receiver<()>, JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let (drop_sender, drop_receiver) = oneshot::channel();
        let drop_sender = Arc::new(Mutex::new(Some(drop_sender)));
        let task = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let io = TokioIo::new(stream);
            let service = service_fn(move |_request: Request<hyper::body::Incoming>| {
                let guard = DropSignal(drop_sender.lock().unwrap().take());
                async move {
                    let body_stream =
                        stream::unfold((0usize, guard), |(index, guard)| async move {
                            sleep(Duration::from_millis(30)).await;
                            let frame = Frame::data(Bytes::from(format!("data: {index}\n\n")));
                            Some((Ok::<_, std::convert::Infallible>(frame), (index + 1, guard)))
                        });
                    let body = StreamBody::new(body_stream).boxed_unsync();
                    Ok::<_, std::convert::Infallible>(
                        Response::builder()
                            .header("content-type", "text/event-stream")
                            .body(body)
                            .unwrap(),
                    )
                }
            });
            let _ = hyper::server::conn::http1::Builder::new()
                .serve_connection(io, service)
                .await;
        });
        (
            format!("http://{address}").parse().unwrap(),
            drop_receiver,
            task,
        )
    }

    fn routed_state(upstream: Uri) -> HashMap<Address, Uri> {
        HashMap::from([(Address::parse("om://demo/model/default").unwrap(), upstream)])
    }

    fn completion_request(address: SocketAddr) -> Request<Full<Bytes>> {
        Request::post(format!("http://{address}/v1/chat/completions"))
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {}", test_token()))
            .header("x-om-tenant", "tenant-a")
            .header("x-om-budget-microcredits", "1000")
            .body(Full::new(Bytes::from_static(
                br#"{"model":"om://demo/model/default","stream":true,"max_tokens":3}"#,
            )))
            .unwrap()
    }

    fn test_token() -> String {
        let token_authority = TokenAuthority::from_secret(TEST_TOKEN_SECRET).unwrap();
        let expires_at_unix_seconds = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
            + 3_600;
        token_authority
            .mint(&Grant {
                tenant: "tenant-a".to_owned(),
                model: "om://demo/model/default".to_owned(),
                budget_microcredits: 10_000,
                max_output_tokens: 64,
                expires_at_unix_seconds,
            })
            .unwrap()
    }

    #[tokio::test]
    async fn oversized_headers_are_rejected_by_the_http_parser() {
        let (address, shutdown, server) = spawn_gateway(HashMap::new()).await;
        let mut socket = TcpStream::connect(address).await.unwrap();
        let request = format!(
            "GET /healthz HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nX-Large: {}\r\n\r\n",
            "x".repeat(MAX_HEADER_BYTES + 1024)
        );
        socket.write_all(request.as_bytes()).await.unwrap();
        let mut response = Vec::new();
        timeout(Duration::from_secs(2), socket.read_to_end(&mut response))
            .await
            .unwrap()
            .unwrap();
        assert!(!response.starts_with(b"HTTP/1.1 200"));
        let _ = shutdown.send(());
        server.await.unwrap().unwrap();
    }

    #[tokio::test]
    async fn oversized_request_bodies_are_rejected() {
        let body = Full::new(Bytes::from(vec![b'x'; MAX_REQUEST_BYTES + 1]));
        assert!(limited_request_body(body, MAX_REQUEST_BYTES).await.is_err());
    }

    #[tokio::test]
    async fn upstream_connect_and_response_header_deadline_is_enforced() {
        let request = std::future::pending::<Result<(), io::Error>>();
        let result = super::upstream_request_with_timeout(request, Duration::from_millis(10)).await;
        assert_eq!(result, Err(UpstreamTimeout::TimedOut));
        assert_eq!(UPSTREAM_CONNECT_TIMEOUT, Duration::from_secs(3));
    }

    #[tokio::test]
    async fn stalled_upstream_body_hits_the_read_timeout() {
        let (polls, on_drop) = (Arc::new(AtomicUsize::new(0)), None);
        let body = ScriptedBody {
            frames: VecDeque::new(),
            polls,
            pending: true,
            on_drop,
        };
        let semaphore = Arc::new(Semaphore::new(1));
        let permit = semaphore.try_acquire_owned().unwrap();
        let mut bounded =
            bounded_response_body_with_limits(body, permit, Duration::from_millis(10), 1024);
        let frame = timeout(Duration::from_secs(1), bounded.frame())
            .await
            .unwrap()
            .unwrap()
            .unwrap_err();
        assert_eq!(
            frame.downcast_ref::<io::Error>().unwrap().kind(),
            io::ErrorKind::TimedOut
        );
    }

    #[tokio::test]
    async fn stream_capacity_rejects_over_limit_admission() {
        let semaphore = Arc::new(Semaphore::new(1));
        let permit = semaphore.clone().try_acquire_owned().unwrap();
        assert!(semaphore.clone().try_acquire_owned().is_err());
        drop(permit);
        assert!(semaphore.try_acquire_owned().is_ok());
    }

    #[tokio::test]
    async fn stream_buffer_cap_preserves_backpressure_between_frames() {
        let polls = Arc::new(AtomicUsize::new(0));
        let body = ScriptedBody {
            frames: VecDeque::from([
                Bytes::from_static(b"ok"),
                Bytes::from(vec![b'x'; MAX_STREAM_FRAME_BYTES + 1]),
            ]),
            polls: polls.clone(),
            pending: false,
            on_drop: None,
        };
        let semaphore = Arc::new(Semaphore::new(1));
        let permit = semaphore.try_acquire_owned().unwrap();
        let mut bounded = bounded_response_body_with_limits(
            body,
            permit,
            Duration::from_secs(1),
            MAX_STREAM_FRAME_BYTES,
        );
        assert_eq!(polls.load(Ordering::Relaxed), 0);
        let first = bounded.frame().await.unwrap().unwrap();
        assert_eq!(first.data_ref().unwrap().as_ref(), b"ok");
        assert_eq!(polls.load(Ordering::Relaxed), 1);
        let oversized = bounded.frame().await.unwrap().unwrap_err();
        assert_eq!(polls.load(Ordering::Relaxed), 2);
        assert_eq!(
            oversized.downcast_ref::<io::Error>().unwrap().kind(),
            io::ErrorKind::InvalidData
        );
    }

    #[tokio::test]
    async fn dropping_downstream_body_cancels_the_upstream_request() {
        let (upstream, cancelled, upstream_task) = spawn_stalling_upstream().await;
        let (address, shutdown, gateway_task) = spawn_gateway(routed_state(upstream)).await;
        let mut socket = TcpStream::connect(address).await.unwrap();
        let payload = br#"{"model":"om://demo/model/default","stream":true}"#;
        let token = test_token();
        let request = format!(
            "POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nAuthorization: Bearer {token}\r\nx-om-tenant: tenant-a\r\nx-om-budget-microcredits: 1000\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            payload.len()
        );
        socket.write_all(request.as_bytes()).await.unwrap();
        socket.write_all(payload).await.unwrap();
        let mut response = Vec::new();
        timeout(Duration::from_secs(2), async {
            while !response.windows(9).any(|window| window == b"data: 0\n\n") {
                let mut buffer = [0u8; 4096];
                let read = socket.read(&mut buffer).await.unwrap();
                assert!(read > 0, "gateway closed before the first SSE chunk");
                response.extend_from_slice(&buffer[..read]);
            }
        })
        .await
        .unwrap();
        drop(socket);
        timeout(Duration::from_secs(2), cancelled)
            .await
            .unwrap()
            .unwrap();
        let _ = shutdown.send(());
        gateway_task.await.unwrap().unwrap();
        upstream_task.abort();
    }

    #[tokio::test]
    async fn graceful_shutdown_drains_an_active_sse_stream() {
        let chunks = ["data: first\n\n", "data: second\n\n", "data: [DONE]\n\n"]
            .map(Bytes::from)
            .to_vec();
        let (upstream, upstream_task) = spawn_finite_upstream(chunks).await;
        let (address, shutdown, gateway_task) = spawn_gateway(routed_state(upstream)).await;
        let client = empty_client();
        let response = client.request(completion_request(address)).await.unwrap();
        let mut body = response.into_body();
        let first = body.frame().await.unwrap().unwrap();
        assert!(first.data_ref().unwrap().starts_with(b"data: first"));
        let _ = shutdown.send(());
        let remaining = body.collect().await.unwrap().to_bytes();
        assert!(remaining.windows(12).any(|part| part == b"data: second"));
        assert!(remaining.windows(12).any(|part| part == b"data: [DONE]"));
        timeout(Duration::from_secs(2), gateway_task)
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        upstream_task.abort();
    }
}
