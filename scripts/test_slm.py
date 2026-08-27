"""Diagnostic tool to test connection and performance of local SLM (llama.cpp) server."""

from __future__ import annotations

import asyncio
import socket
import sys
import time
from urllib.parse import urlparse

import httpx
from langchain_core.messages import HumanMessage

from tars.adapters.llamacpp import LlamaCppAdapter
from tars.config import get_settings


async def test_tcp_connectivity(host: str, port: int) -> bool:
    """Test raw TCP socket connection to the target host and port."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception as err:
        print(f"  [!] TCP 소켓 연결 중 에러: {err}")
        return False


async def test_endpoint(client: httpx.AsyncClient, name: str, url: str) -> tuple[bool, int, str, float]:
    """Test a specific HTTP endpoint and return success, status code, response body preview, and elapsed ms."""
    start = time.perf_counter()
    try:
        res = await client.get(url, timeout=3.0)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        preview = res.text[:200].replace("\n", " ").strip()
        return res.is_success, res.status_code, preview, elapsed_ms
    except httpx.ConnectError:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return False, 0, "Connection refused (서버가 실행 중이지 않거나 포트가 닫혀 있습니다)", elapsed_ms
    except httpx.TimeoutException:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return False, 0, "Timeout (> 3.0s)", elapsed_ms
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return False, 0, f"Error: {exc}", elapsed_ms


async def main() -> None:
    settings = get_settings()
    base_url = settings.llamacpp_base_url
    model_name = settings.llamacpp_model_name

    print("=" * 70)
    print("🔍 TARS Local SLM (llama.cpp) 연결 진단 테스트")
    print("=" * 70)
    print(f"• 설정된 Base URL   : {base_url}")
    print(f"• 설정된 Model Name : {model_name}")

    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    print(f"• 대상 호스트/포트  : {host}:{port}")
    print("-" * 70)

    # 1. TCP 연결 확인
    print(f"\n[1단계: TCP 포트 연결 확인] {host}:{port} ...")
    is_tcp_ok = await test_tcp_connectivity(host, port)
    if is_tcp_ok:
        print(f"  ✅ {host}:{port} 포트가 열려 있으며 접속 가능합니다.")
    else:
        print(f"  ❌ {host}:{port} 포트에 연결할 수 없습니다!")
        print("  💡 로컬 SLM 서버(llama.cpp, LM Studio, Ollama 등)가 실제로 실행 중인지 확인하세요.")
        print(f"     실행 예시: llama-server -m your_model.gguf --port {port}")
        print("=" * 70)
        sys.exit(1)

    # 2. HTTP 엔드포인트 프로브
    print("\n[2단계: HTTP 헬스체크 및 모델 엔드포인트 점검]")
    root_url = base_url[:-3] if base_url.endswith("/v1") else base_url
    v1_url = base_url if base_url.endswith("/v1") else f"{base_url}/v1"

    endpoints_to_probe = [
        ("루트 헬스체크", f"{root_url}/health"),
        ("v1 헬스체크", f"{v1_url}/health"),
        ("v1 모델 목록", f"{v1_url}/models"),
        ("루트 모델 목록", f"{root_url}/models"),
    ]

    async with httpx.AsyncClient() as client:
        for desc, url in endpoints_to_probe:
            success, code, body, ms = await test_endpoint(client, desc, url)
            status_mark = "✅" if success else "⚠️" if code == 404 else "❌"
            print(f"  {status_mark} {desc:<12} | URL: {url:<35} | 상태: {code or 'ERR':<3} ({ms:.1f}ms)")
            if body and success:
                print(f"     응답 내용: {body[:120]}")

    # 3. LlamaCppAdapter 작동 테스트
    print("\n[3단계: LlamaCppAdapter 통합 테스트]")
    adapter = LlamaCppAdapter(base_url=base_url, model_name=model_name, timeout_ms=1000)

    # 3-1. is_healthy()
    start = time.perf_counter()
    healthy = await adapter.is_healthy()
    health_ms = (time.perf_counter() - start) * 1000.0
    if healthy:
        print(f"  ✅ LlamaCppAdapter.is_healthy() -> 성공! ({health_ms:.1f}ms)")
    else:
        print(f"  ❌ LlamaCppAdapter.is_healthy() -> 실패 ({health_ms:.1f}ms)")
        print("     (헬스체크 엔드포인트 응답이 없거나 타임아웃을 초과했습니다)")

    # 3-2. agenerate() 단일 응답
    print("\n[4단계: 텍스트 생성 테스트 (agenerate)]")
    test_message = [HumanMessage(content="Say 'TARS online' in 5 words or less.")]
    start = time.perf_counter()
    try:
        res_text = await adapter.agenerate(messages=test_message, system_prompt="You are TARS.")
        gen_ms = (time.perf_counter() - start) * 1000.0
        print(f"  ✅ 응답 성공 ({gen_ms:.1f}ms):")
        print(f"     \"{res_text.strip()}\"")
    except Exception as e:
        gen_ms = (time.perf_counter() - start) * 1000.0
        print(f"  ❌ 응답 실패 ({gen_ms:.1f}ms): {e}")

    # 3-3. astream() 실시간 스트리밍
    print("\n[5단계: 실시간 토큰 스트리밍 테스트 (astream)]")
    stream_message = [HumanMessage(content="Count from 1 to 5.")]
    start = time.perf_counter()
    first_token_time = None
    chunks: list[str] = []
    try:
        print("  출력: ", end="", flush=True)
        async for chunk in adapter.astream(messages=stream_message, system_prompt="You are TARS."):
            if first_token_time is None:
                first_token_time = (time.perf_counter() - start) * 1000.0
            print(chunk, end="", flush=True)
            chunks.append(chunk)
        total_stream_ms = (time.perf_counter() - start) * 1000.0
        print("\n")
        ttft_str = f"{first_token_time:.1f}ms" if first_token_time is not None else "N/A"
        print(f"  ✅ 스트리밍 완료 (첫 토큰 지연 TTFT: {ttft_str}, 전체 소요: {total_stream_ms:.1f}ms, 청크 수: {len(chunks)})")
    except Exception as e:
        print(f"\n  ❌ 스트리밍 실패: {e}")

    print("\n" + "=" * 70)
    print("📋 진단 결과 요약")
    print("=" * 70)
    if healthy and chunks:
        print("🎉 로컬 SLM (llama.cpp) 연결 및 스트리밍이 정상적으로 작동합니다!")
    elif is_tcp_ok:
        print("⚠️ 포트 연결은 성공했으나, 모델 응답이나 헬스체크에 실패했습니다.")
        print("  - 서버 콘솔 로그에서 모델이 정상 로드되었는지 확인하세요.")
        print("  - OpenAI 호환 API 엔드포인트(/v1/chat/completions)가 활성화되어 있는지 확인하세요.")
    else:
        print("❌ 서버 포트에 접속할 수 없습니다. SLM 서버 실행 상태를 확인해주세요.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
