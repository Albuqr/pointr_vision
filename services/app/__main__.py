import argparse

import uvicorn

from services.app.server import create_app


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m services.app")
    parser.add_argument("--out", default="C:/pointr_sessions")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    app = create_app(args.out)
    app.state.open_browser_url = f"http://127.0.0.1:{args.port}/"
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
