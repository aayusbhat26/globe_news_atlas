# Globe News Atlas frontend

React 19 + TypeScript + Vite client for the Globe News Atlas API.

```bash
npm ci
npm run dev      # http://localhost:5173, proxies API calls to http://localhost:8000/v1
npm run build    # production build in dist/, served by the FastAPI app
npm run lint
```

The client has no bundled event data. It reads `/v1/snapshot`, `/v1/events/{id}`, and `/v1/search`; when the API is unavailable the UI shows an error banner rather than sample content.

See the repository [README](../README.md) for full setup, storage, and pipeline documentation.
