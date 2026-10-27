use std::{convert::Infallible, error::Error, net::SocketAddr};

use bytes::Bytes;
use futures_util::stream;
use http_body_util::{combinators::UnsyncBoxBody, BodyExt, Full, Limited, StreamBody};
use hyper::{
    body::{Frame, Incoming},
    header::{HeaderValue, CONTENT_TYPE},
    service::service_fn,
    Method, Request, Response, StatusCode,
};
use hyper_util::rt::TokioIo;
use serde_json::{json, Value};
use tokio::{
    net::TcpListener,
    task::JoinSet,
    time::{sleep, timeout, Duration},
};

type BoxError = Box<dyn Error + Send + Sync>;
type ModelBody = UnsyncBoxBody<Bytes, BoxError>;
const MAX_REQUEST_BYTES: usize = 1024 * 1024;

fn full_body(value: impl Into<Bytes>) -> ModelBody {
    Full::new(value.into())
        .map_err(|never: Infallible| match never {})
        .boxed_unsync()
}

fn json_response(status: StatusCode, value: Value) -> Response<ModelBody> {
    let mut response = Response::new(full_body(Bytes::from(value.to_string())));
    *response.status_mut() = status;
    response
        .headers_mut()
        .insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
    response
}

fn request_id(request: &Request<Incoming>) -> String {
    request
        .headers()
        .get("x-request-id")
        .and_then(|value| value.to_str().ok())
        .unwrap_or("missing")
        .to_owned()
}

async fn handle_inner(request: Request<Incoming>) -> Response<ModelBody> {
    match (request.method().clone(), request.uri().path()) {
        (Method::GET, "/healthz") => json_response(
            StatusCode::OK,
            json!({"status":"ok","service":"om-mock-model"}),
        ),
        (Method::POST, "/v1/chat/completions") => {
            let id = request_id(&request);
            let collected = Limited::new(request.into_body(), MAX_REQUEST_BYTES)
                .collect()
                .await;
            let body = match collected {
                Ok(body) => body.to_bytes(),
                Err(_) => {
                    return json_response(
                        StatusCode::PAYLOAD_TOO_LARGE,
                        json!({"error":{"code":"OS-0001","message":"request body exceeds 1 MiB"}}),
                    );
                }
            };
            let value: Value = match serde_json::from_slice(&body) {
                Ok(value) => value,
                Err(_) => {
                    return json_response(
                        StatusCode::BAD_REQUEST,
                        json!({"error":{"code":"OS-0001","message":"request body must be JSON"}}),
                    );
                }
            };
            let token_count = value
                .get("max_tokens")
                .and_then(Value::as_u64)
                .unwrap_or(3)
                .clamp(1, 32) as usize;
            if value.get("stream").and_then(Value::as_bool) != Some(true) {
                return json_response(
                    StatusCode::OK,
                    json!({
                        "id":"chatcmpl-om-mock",
                        "object":"chat.completion",
                        "choices":[{"index":0,"message":{"role":"assistant","content":"Rust mock response"},"finish_reason":"stop"}]
                    }),
                );
            }
            let tokens = ["Rust", "gateway", "stream", "is", "working"];
            println!(
                "{}",
                json!({"level":"info","service":"om-mock-model","event":"completion","request_id":id})
            );
            let frames = stream::unfold((0usize, token_count), move |(index, count)| async move {
                if index < count {
                    sleep(Duration::from_millis(120)).await;
                    let token = tokens[index % tokens.len()];
                    let payload = json!({
                        "id":"chatcmpl-om-mock",
                        "object":"chat.completion.chunk",
                        "choices":[{"index":0,"delta":{"content":token},"finish_reason":null}]
                    });
                    let frame = format!("data: {payload}\n\n");
                    Some((
                        Ok::<Frame<Bytes>, Infallible>(Frame::data(Bytes::from(frame))),
                        (index + 1, count),
                    ))
                } else if index == count {
                    Some((
                        Ok::<Frame<Bytes>, Infallible>(Frame::data(Bytes::from_static(
                            b"data: [DONE]\n\n",
                        ))),
                        (index + 1, count),
                    ))
                } else {
                    None
                }
            });
            let body = StreamBody::new(frames)
                .map_err(|never: Infallible| match never {})
                .boxed_unsync();
            let mut response = Response::new(body);
            *response.status_mut() = StatusCode::OK;
            response.headers_mut().insert(
                CONTENT_TYPE,
                HeaderValue::from_static("text/event-stream; charset=utf-8"),
            );
            response
                .headers_mut()
                .insert("cache-control", HeaderValue::from_static("no-cache"));
            response
        }
        _ => json_response(
            StatusCode::NOT_FOUND,
            json!({"error":{"code":"OS-0001","message":"endpoint is not available"}}),
        ),
    }
}

async fn handle(request: Request<Incoming>) -> Result<Response<ModelBody>, Infallible> {
    Ok(handle_inner(request).await)
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
    let address = std::env::var("OM_MOCK_LISTEN")
        .unwrap_or_else(|_| "127.0.0.1:8081".to_owned())
        .parse::<SocketAddr>()?;
    let listener = TcpListener::bind(address).await?;
    let mut connections = JoinSet::new();
    let shutdown = shutdown_signal();
    tokio::pin!(shutdown);
    println!(
        "{}",
        json!({"level":"info","service":"om-mock-model","event":"listening","address":address})
    );

    loop {
        tokio::select! {
            _ = &mut shutdown => break,
            joined = connections.join_next(), if !connections.is_empty() => {
                if let Some(Err(error)) = joined {
                    eprintln!("{{\"level\":\"error\",\"service\":\"om-mock-model\",\"event\":\"connection_task_failed\",\"error\":{}}}", json!(error.to_string()));
                }
            }
            accepted = listener.accept() => {
                let (stream, _) = accepted?;
                connections.spawn(async move {
                    let service = service_fn(handle);
                    let builder = hyper::server::conn::http1::Builder::new();
                    if let Err(error) = builder
                        .serve_connection(TokioIo::new(stream), service)
                        .await
                    {
                        eprintln!("{{\"level\":\"warn\",\"service\":\"om-mock-model\",\"event\":\"connection_closed\",\"error\":{}}}", json!(error.to_string()));
                    }
                });
            }
        }
    }

    let drained = timeout(Duration::from_secs(5), async {
        while connections.join_next().await.is_some() {}
    })
    .await;
    if drained.is_err() {
        connections.abort_all();
        while connections.join_next().await.is_some() {}
    }
    println!(
        "{}",
        json!({"level":"info","service":"om-mock-model","event":"shutdown_complete"})
    );
    Ok(())
}
