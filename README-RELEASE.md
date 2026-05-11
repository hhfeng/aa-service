# aa-service (Standalone Release)

A FastAPI HTTP service exposing one or more `graphify` knowledge bases over a small REST API.

## Getting Started

1.  **Extract the archive** to a folder of your choice.
2.  **Configure your Knowledge Bases**: Edit the included `kbs.json` file.
3.  **Run the service**:
    *   **Linux/macOS**: `./aa-service`
    *   **Windows**: `aa-service.exe`

The service will start at `http://127.0.0.1:8000` by default.

---

## Configuration (`kbs.json`)

Edit `kbs.json` in the same directory as the executable to add your Knowledge Bases:

```json
{
  "myproject_kb": {
    "name": "My Project",
    "graphify_out": "/path/to/your/kb/graphify-out",
    "raw": "/path/to/your/kb/raw"
  }
}
```

*   `name`: Human-readable display name.
*   `graphify_out`: Absolute path to the `graphify-out/` directory containing `graph.json` or `graph.db`.
*   `raw`: Absolute path to the source files; needed for `/update` and `/add` endpoints.

---

## Command Line Options

You can pass arguments to change the host and port:

```bash
./aa-service --host 0.0.0.0 --port 9000
```

*   `--host`: Bind address (default `127.0.0.1`). Use `0.0.0.0` to expose on the network.
*   `--port`: TCP port (default `8000`).

---

## Quick API Test

Once running, you can test the service using `curl`:

### Discovery
```bash
curl -s http://127.0.0.1:8000/
```

### Query the graph
```bash
curl -s -X POST http://127.0.0.1:8000/kb/myproject_kb/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "what is this project about?", "mode": "bfs"}'
```

---

## Security

If you expose the service on a network (`--host 0.0.0.0`), it is strongly recommended to set an API key:

1.  Set the environment variable `GRAPHIFY_SERVICE_API_KEY`.
2.  Every request must then include the header `X-API-Key: <your-key>`.
