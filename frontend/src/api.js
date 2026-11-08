// Small wrapper around the backend REST API and WebSocket feed.

export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const WS_URL = API_URL.replace(/^http/, "ws") + "/ws/transactions";

async function request(path, options = {}) {
  const resp = await fetch(API_URL + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) throw new Error(`${options.method || "GET"} ${path} failed: ${resp.status}`);
  return resp.json();
}

export const api = {
  listTransactions: (limit = 100) => request(`/api/v1/transactions?limit=${limit}`),
  stats: () => request("/api/v1/stats"),
  model: () => request("/api/v1/model"),
  review: (transactionId, status) =>
    request(`/api/v1/transactions/${encodeURIComponent(transactionId)}/review`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
};

// Opens the live feed and reconnects automatically if the connection drops.
export function connectFeed(onMessage, onStatus) {
  let socket;
  let retryTimer;
  let closed = false;

  const open = () => {
    socket = new WebSocket(WS_URL);
    socket.onopen = () => onStatus("live");
    socket.onmessage = (event) => onMessage(JSON.parse(event.data));
    socket.onclose = () => {
      onStatus("reconnecting");
      if (!closed) retryTimer = setTimeout(open, 2000);
    };
    socket.onerror = () => socket.close();
  };
  open();

  return () => {
    closed = true;
    clearTimeout(retryTimer);
    socket?.close();
  };
}
