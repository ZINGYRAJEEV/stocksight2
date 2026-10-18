export type Quote = { id?: string; name: string; symbol?: string; available?: boolean; value?: number; change?: number; changePct?: number; week52Low?: number; week52High?: number; sparkline?: number[]; wtdPct?: number; ytdPct?: number };
export type Report = { asOf: string; marketStatus: string; indices: Quote[]; sentiment: { score: number; label: string; source: string }; intraday: { name: string; points: { time: string; value: number }[] }[]; indicators: (Quote & { label: string; unit?: string; asOf?: string })[]; sectors: { name: string; value: number }[]; highlights: string[]; events: { time: string; title: string; detail: string }[]; movers: { gainers: { ticker: string; changePct: number; tag: string }[]; losers: { ticker: string; changePct: number; tag: string }[] }; oneLine: string; sources: string[] };

const API_URL = import.meta.env.VITE_MARKET_API_URL ?? "http://localhost:8000/api/market-report";
export async function getReport(): Promise<Report> {
  const response = await fetch(API_URL);
  if (!response.ok) throw new Error("Market data is temporarily unavailable");
  return response.json() as Promise<Report>;
}
