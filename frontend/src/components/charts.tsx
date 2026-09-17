import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

const GRID = "#94a3b8";
const TICK = { fill: "#64748b", fontSize: 11 } as const;

interface Series {
  name: string;
  color: string;
  x: number[];
  y: number[];
}

export function ChartCard({ title, hint, children, className = "" }: {
  title: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`card ${className}`}>
      <div className="card-header flex items-center justify-between gap-2">
        <span>{title}</span>
        {hint && <span className="font-normal normal-case text-slate-400">{hint}</span>}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function alignedRows(series: Series[], gridPoints = 90): Record<string, number | string | null>[] {
  const xs = series.flatMap((s) => s.x);
  if (xs.length === 0) return [];
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  const pad = hi === lo ? 0.5 : (hi - lo) * 0.05;
  const grid = Array.from({ length: gridPoints }, (_, i) => lo - pad + ((hi - lo + 2 * pad) * i) / (gridPoints - 1));
  const rows: Record<string, number | string | null>[] = grid.map((x) => ({ x }));
  for (const s of series) {
    for (let g = 0; g < grid.length; g++) {
      rows[g][s.name] = interpolate(s.x, s.y, grid[g]);
    }
  }
  return rows;
}

function interpolate(xs: number[], ys: number[], target: number): number | null {
  if (xs.length === 0) return null;
  if (target <= xs[0]) return ys[0];
  if (target >= xs[xs.length - 1]) return ys[xs.length - 1];
  for (let i = 1; i < xs.length; i++) {
    if (target <= xs[i]) {
      const t = (target - xs[i - 1]) / (xs[i] - xs[i - 1] || 1);
      return ys[i - 1] + t * (ys[i] - ys[i - 1]);
    }
  }
  return ys[ys.length - 1];
}

const X_NUM = { type: "number" as const, dataKey: "x", domain: ["dataMin", "dataMax"] as [string, string] };
const fmtX = (v: number) => (Math.abs(v) < 10 ? v.toFixed(3) : v.toFixed(2));

function chartTooltip() {
  return {
    contentStyle: {
      background: "#0f172a",
      border: "1px solid #334155",
      borderRadius: 8,
      color: "#e2e8f0",
      fontSize: 12,
    },
    labelFormatter: (v: number) => `x = ${fmtX(v)}`,
  };
}

export function KdeChart({ series, height = 220 }: { series: Series[]; height?: number }) {
  const rows = alignedRows(series);
  const safe = (name: string) => name.replace(/\W/g, "");
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={rows} margin={{ top: 5, right: 8, left: -18, bottom: 0 }}>
        <defs>
          {series.map((s) => (
            <linearGradient key={s.name} id={`grad-${safe(s.name)}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke={GRID} strokeOpacity={0.15} vertical={false} />
        <XAxis {...X_NUM} tick={TICK} tickLine={false} axisLine={false} tickFormatter={fmtX} />
        <YAxis tick={TICK} tickLine={false} axisLine={false} width={40} />
        <Tooltip {...chartTooltip()} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {series.map((s) => (
          <Area
            key={s.name}
            type="monotone"
            dataKey={s.name}
            stroke={s.color}
            strokeWidth={2}
            fill={`url(#grad-${safe(s.name)})`}
            isAnimationActive={false}
            dot={false}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function HistogramChart({ series, height = 220 }: { series: Series[]; height?: number }) {
  const rows = alignedRows(series);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 5, right: 8, left: -18, bottom: 0 }} barCategoryGap="20%">
        <CartesianGrid stroke={GRID} strokeOpacity={0.15} vertical={false} />
        <XAxis {...X_NUM} tick={TICK} tickLine={false} axisLine={false} tickFormatter={fmtX} />
        <YAxis tick={TICK} tickLine={false} axisLine={false} width={40} />
        <Tooltip {...chartTooltip()} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {series.map((s) => (
          <Bar key={s.name} dataKey={s.name} fill={s.color} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function HistogramWithThreshold({ x, y, color, threshold, height = 220, label }: {
  x: number[];
  y: number[];
  color: string;
  threshold?: number;
  height?: number;
  label: string;
}) {
  const rows = x.map((v, i) => ({ bucket: v.toFixed(3), count: y[i] }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 5, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeOpacity={0.15} vertical={false} />
        <XAxis dataKey="bucket" tick={TICK} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={24} />
        <YAxis tick={TICK} tickLine={false} axisLine={false} width={44} />
        <Tooltip
          contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, color: "#e2e8f0", fontSize: 12 }}
        />
        {threshold !== undefined && (
          <ReferenceLine
            x={threshold.toFixed(3)}
            stroke="#f43f5e"
            strokeDasharray="4 3"
            label={{ value: "possible-contamination threshold", fill: "#f43f5e", fontSize: 10, position: "insideTopRight" }}
          />
        )}
        <Bar dataKey="count" fill={color} isAnimationActive={false} name={label} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function LossScatter({ pairs, height = 240 }: { pairs: [number, number][]; height?: number }) {
  const rows = pairs.map(([original, mutated], index) => ({ original, mutated, index }));
  const max = Math.max(...pairs.flat(), 1) * 1.05;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 10, right: 12, left: -8, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeOpacity={0.15} />
        <XAxis type="number" dataKey="original" name="original loss" tick={TICK} tickLine={false} axisLine={false}
          domain={[0, "dataMax"]} />
        <YAxis type="number" dataKey="mutated" name="mean mutated loss" tick={TICK} tickLine={false} axisLine={false}
          domain={[0, "dataMax"]} />
        <ZAxis range={[40, 40]} />
        <ReferenceLine segment={[{ x: 0, y: 0 }, { x: max, y: max }]} stroke="#64748b" strokeDasharray="4 4"
          label={{ value: "y = x", fill: "#64748b", fontSize: 10, position: "insideBottomRight" }} />
        <Tooltip
          cursor={{ strokeDasharray: "3 3" }}
          contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, color: "#e2e8f0", fontSize: 12 }}
        />
        <Scatter data={rows} fill="#8b5cf6" fillOpacity={0.75} isAnimationActive={false} />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

export function ZScoreChart({ zScores, color = "#38bdf8", height = 200 }: { zScores: number[]; color?: string; height?: number }) {
  const rows = zScores.map((z, index) => ({ z, index }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={rows} margin={{ top: 5, right: 8, left: -20, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeOpacity={0.15} vertical={false} />
        <XAxis dataKey="index" tick={false} tickLine={false} axisLine={false} />
        <YAxis tick={TICK} tickLine={false} axisLine={false} width={46} />
        <ReferenceLine y={2} stroke="#f43f5e" strokeDasharray="4 3" label={{ value: "z = 2", fill: "#f43f5e", fontSize: 10 }} />
        <ReferenceLine y={0} stroke="#64748b" />
        <Tooltip
          contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, color: "#e2e8f0", fontSize: 12 }}
        />
        <Line type="monotone" dataKey="z" stroke={color} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function ClassificationCounts({ counts, height = 210 }: { counts: Record<string, number>; height?: number }) {
  const order = ["LOW_EVIDENCE", "NORMAL", "ELEVATED", "POSSIBLE_CONTAMINATION", "HIGH_CONTAMINATION_SIGNAL"];
  const colors: Record<string, string> = {
    LOW_EVIDENCE: "#94a3b8",
    NORMAL: "#64748b",
    ELEVATED: "#f59e0b",
    POSSIBLE_CONTAMINATION: "#f97316",
    HIGH_CONTAMINATION_SIGNAL: "#f43f5e",
  };
  const rows = order
    .filter((key) => (counts[key] ?? 0) > 0)
    .map((key) => ({ key, count: counts[key] ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} layout="vertical" margin={{ top: 5, right: 24, left: 24, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeOpacity={0.12} horizontal={false} />
        <XAxis type="number" tick={TICK} tickLine={false} axisLine={false} allowDecimals={false} />
        <YAxis type="category" dataKey="key" width={130} tick={{ fill: "#94a3b8", fontSize: 9 }} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, color: "#e2e8f0", fontSize: 12 }}
        />
        {rows.map((row) => (
          <Bar key={row.key} dataKey="count" fill={colors[row.key] ?? "#8b5cf6"} name={row.key} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

type SignalPoint = {
  label: string;
  contaminationIndex: number | null;
  effectSize: number | null;
  classification: string;
};

const CLASS_COLORS: Record<string, string> = {
  LOW_EVIDENCE: "#94a3b8",
  NORMAL: "#64748b",
  ELEVATED: "#f59e0b",
  POSSIBLE_CONTAMINATION: "#f97316",
  HIGH_CONTAMINATION_SIGNAL: "#f43f5e",
};

export function SignalRankingChart({ points, height = 230 }: { points: SignalPoint[]; height?: number }) {
  const rows = points
    .filter((point) => point.contaminationIndex !== null && Number.isFinite(point.contaminationIndex))
    .sort((a, b) => (b.contaminationIndex ?? -Infinity) - (a.contaminationIndex ?? -Infinity))
    .slice(0, 12)
    .reverse();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} layout="vertical" margin={{ top: 5, right: 24, left: 18, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeOpacity={0.12} horizontal={false} />
        <XAxis type="number" dataKey="contaminationIndex" tick={TICK} tickLine={false} axisLine={false} tickFormatter={fmtX} />
        <YAxis type="category" dataKey="label" width={96} tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, color: "#e2e8f0", fontSize: 12 }}
          labelFormatter={(value) => `snippet: ${String(value)}`}
          formatter={(value: number) => [fmtX(value), "CI"]}
        />
        <ReferenceLine x={0.15} stroke="#f97316" strokeDasharray="4 3" />
        <ReferenceLine x={0.35} stroke="#f43f5e" strokeDasharray="4 3" />
        <Bar dataKey="contaminationIndex" name="CI" isAnimationActive={false}>
          {rows.map((row) => <Cell key={row.label} fill={CLASS_COLORS[row.classification] ?? "#8b5cf6"} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SignalEffectScatter({ points, height = 230 }: { points: SignalPoint[]; height?: number }) {
  const rows = points
    .filter((point) => Number.isFinite(point.contaminationIndex) && Number.isFinite(point.effectSize))
    .map((point) => ({ ci: point.contaminationIndex as number, effect: point.effectSize as number, ...point }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 10, right: 12, left: -8, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeOpacity={0.15} />
        <XAxis type="number" dataKey="ci" name="contamination index" tick={TICK} tickLine={false} axisLine={false} tickFormatter={fmtX} />
        <YAxis type="number" dataKey="effect" name="standardized gap" tick={TICK} tickLine={false} axisLine={false} />
        <ReferenceLine x={0} stroke="#64748b" />
        <ReferenceLine y={0} stroke="#64748b" />
        <Tooltip
          {...chartTooltip()}
          formatter={(value: number, name: string) => [fmtX(value), name]}
          labelFormatter={(_, payload) => payload?.[0]?.payload?.label ?? "snippet"}
        />
        <Scatter data={rows} isAnimationActive={false} name="Snippet">
          {rows.map((row) => <Cell key={row.label} fill={CLASS_COLORS[row.classification] ?? "#8b5cf6"} />)}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  );
}

export { ReferenceLine };
