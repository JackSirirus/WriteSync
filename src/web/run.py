"""Web UI 启动入口: python -m src.web.run"""
import uvicorn

def main():
    uvicorn.run(
        "src.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        timeout_keep_alive=300,   # SSE 长连接保活: 5 分钟无数据不超时
        timeout_graceful_shutdown=10,
    )

if __name__ == "__main__":
    main()
