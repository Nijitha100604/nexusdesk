import { useEffect, useState } from "react";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export default function App() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <main className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="bg-white shadow rounded-xl p-8 max-w-md w-full">
        <h1 className="text-2xl font-bold text-slate-800">NexusDesk</h1>
        <p className="text-slate-500 mb-4">Autonomous Multi-Agent IT Helpdesk</p>
        {error && <p className="text-red-600">Backend unreachable: {error}</p>}
        {health && (
          <pre className="text-sm bg-slate-100 rounded p-3">
            {JSON.stringify(health, null, 2)}
          </pre>
        )}
        {!health && !error && <p className="text-slate-400">Checking backend...</p>}
      </div>
    </main>
  );
}
