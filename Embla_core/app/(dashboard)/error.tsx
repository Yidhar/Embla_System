"use client";
export default function DashboardError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="p-8 text-center">
      <h2 className="text-lg font-semibold text-red-400 mb-2">Dashboard Error</h2>
      <p className="text-zinc-400 mb-4">{error.message}</p>
      <button onClick={reset} className="px-4 py-2 bg-zinc-700 rounded hover:bg-zinc-600">Retry</button>
    </div>
  );
}
