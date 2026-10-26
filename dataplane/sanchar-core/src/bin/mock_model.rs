//! Async Rust upstream used by the integrated dev stack and D5 load harness.

use std::{convert::Infallible, net::SocketAddr};

use bytes::Bytes;
use futures_util::{stream, StreamExt};
use http_body_util::{combinators::UnsyncBoxBody, BodyExt, Full, StreamBody};
use hyper::{
    body::{Frame, Incoming},
    service::service_fn,
    Method, Request, Response, StatusCode,
};
use hyper_util::rt::TokioIo;
use serde_json::{json, Value};
use tokio::net::TcpListener;

type ResponseBody = UnsyncBoxBody<Bytes, Infallible>;

fn full(body: impl Into<Bytes>) -> ResponseBody {
    Full::new(body.into()).boxed_unsync()
}

fn response(
    status: StatusCode,
    content_type: &'static str,
    body: impl Into<Bytes>,
) -> Response<ResponseBody> {
    Response::builder()
        .status(status)
        .header("content-type", content_type)
        .body(full(body))
        .expect("static mock response is valid")
}

async fn handle(request: Request<Incoming>) -> Result<Response<ResponseBody>, Infallible> {
    let path = request.uri().path().to_owned();
    match (request.method(), path.as_str()) {
        (&Method::GET, "/healthz") => Ok(response(
            StatusCode::OK,
            "application/json",
            Bytes::from_static(b"{\"status\":\"ok\"}"),
        )),
        (&Method::POST, "/v1/chat/completions") => {
            let chunks = stream::iter(1..=500).map(|index| {
                let payload = format!(
                    "id: {index}\nevent: delta\ndata: {{\"seq\":{index},\"delta\":\"token-{index}\"}}\n\n"
                );
                Ok::<Frame<Bytes>, Infallible>(Frame::data(Bytes::from(payload)))
            });
            let body = StreamBody::new(chunks).boxed_unsync();
            Ok(Response::builder()
                .status(StatusCode::OK)
                .header("content-type", "text/event-stream; charset=utf-8")
                .header("cache-control", "no-cache")
                .body(body)
                .expect("static mock response is valid"))
        }
        (&Method::POST, "/mcp") => {
            let collected = request.into_body().collect().await;
            let request_value: Value = collected
                .map(|body| body.to_bytes())
                .ok()
                .and_then(|body| serde_json::from_slice(&body).ok())
                .unwrap_or(Value::Null);
            let id = request_value.get("id").cloned().unwrap_or(Value::Null);
            let result = json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": {"content": [{"type": "text", "text": "mock-tool-ok"}]}
            });
            Ok(response(
                StatusCode::OK,
                "application/json",
                Bytes::from(result.to_string()),
            ))
        }
        (&Method::GET, "/fanout") => {
            let fanout = request
                .uri()
                .query()
                .unwrap_or_default()
                .split('&')
                .find_map(|item| item.strip_prefix("n="))
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(16)
                .clamp(1, 32);
            let result = json!({
                "results": (0..fanout).map(|index| json!({"branch": index, "status": "ok"})).collect::<Vec<_>>()
            });
            Ok(response(
                StatusCode::OK,
                "application/json",
                Bytes::from(result.to_string()),
            ))
        }
        _ => Ok(response(
            StatusCode::NOT_FOUND,
            "application/json",
            Bytes::from_static(b"{\"error\":\"not_found\"}"),
        )),
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let port = std::env::var("OM_MOCK_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or(8081);
    let address = SocketAddr::from(([0, 0, 0, 0], port));
    let listener = TcpListener::bind(address).await?;
    eprintln!("Rust mock model listening on {address}");

    loop {
        let (socket, _) = listener.accept().await?;
        tokio::spawn(async move {
            let service = service_fn(handle);
            if let Err(error) = hyper::server::conn::http1::Builder::new()
                .serve_connection(TokioIo::new(socket), service)
                .await
            {
                eprintln!("mock connection ended: {error}");
            }
        });
    }
}
