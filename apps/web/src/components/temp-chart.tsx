/**
 * Temperature trend.
 *
 * Hand-drawn SVG rather than a chart library: the series is one line with two threshold
 * rules, and a dependency that renders on the client would cost more than it earns on a
 * server-rendered page.
 */
import { Mono } from "@/components/ui";

interface Reading {
  id: string;
  celsius: number;
  recorded_at: string;
}

export function TemperatureChart({
  readings,
  setpoint,
  alarmHigh,
  height = 180,
}: {
  readings: Reading[];
  setpoint: number;
  alarmHigh: number;
  height?: number;
}) {
  if (readings.length < 2) {
    return (
      <div className="px-4 py-10 text-center text-[13px] text-[#737373]">
        Not enough readings to plot a trend yet.
      </div>
    );
  }

  const width = 1000;
  const pad = { top: 12, right: 12, bottom: 22, left: 44 };
  const inner = { w: width - pad.left - pad.right, h: height - pad.top - pad.bottom };

  const temps = readings.map((r) => r.celsius);
  const lo = Math.min(...temps, setpoint, alarmHigh) - 3;
  const hi = Math.max(...temps, alarmHigh) + 3;
  const span = hi - lo || 1;

  const x = (i: number) => pad.left + (i / (readings.length - 1)) * inner.w;
  const y = (c: number) => pad.top + (1 - (c - lo) / span) * inner.h;

  const path = readings.map((r, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(r.celsius).toFixed(1)}`).join(" ");
  const area = `${path} L${x(readings.length - 1).toFixed(1)},${(pad.top + inner.h).toFixed(1)} L${pad.left},${(pad.top + inner.h).toFixed(1)} Z`;

  const latest = readings[readings.length - 1];
  const breached = latest.celsius > alarmHigh;
  const stroke = breached ? "#dc2626" : "#2563eb";

  const firstBreachIndex = readings.findIndex((r) => r.celsius > alarmHigh);

  return (
    <div>
      <div className="scroll-x">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full min-w-[520px]"
          role="img"
          aria-label={`Temperature trend for the failed freezer. Latest reading ${latest.celsius.toFixed(1)} degrees Celsius against an alarm threshold of ${alarmHigh} degrees.`}
        >
          <defs>
            <linearGradient id="tempFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity="0.14" />
              <stop offset="100%" stopColor={stroke} stopOpacity="0" />
            </linearGradient>
          </defs>

          {[setpoint, alarmHigh].map((value, index) => (
            <g key={value}>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={y(value)}
                y2={y(value)}
                stroke={index === 1 ? "#ea580c" : "#e5e5e5"}
                strokeWidth="1"
                strokeDasharray={index === 1 ? "4 4" : "0"}
              />
              <text
                x={pad.left - 6}
                y={y(value) + 4}
                textAnchor="end"
                fontSize="11"
                fill={index === 1 ? "#ea580c" : "#a3a3a3"}
                fontFamily="var(--font-geist-mono)"
              >
                {value.toFixed(0)}
              </text>
            </g>
          ))}

          {firstBreachIndex > 0 ? (
            <line
              x1={x(firstBreachIndex)}
              x2={x(firstBreachIndex)}
              y1={pad.top}
              y2={pad.top + inner.h}
              stroke="#dc2626"
              strokeWidth="1"
              strokeDasharray="2 3"
              opacity="0.55"
            />
          ) : null}

          <path d={area} fill="url(#tempFill)" />
          <path d={path} fill="none" stroke={stroke} strokeWidth="1.75" strokeLinejoin="round" />
          <circle cx={x(readings.length - 1)} cy={y(latest.celsius)} r="3.5" fill={stroke} />
        </svg>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px] text-[#737373]">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-[2px] w-4" style={{ background: stroke }} />
          latest <Mono className="text-[11px]">{latest.celsius.toFixed(1)}°C</Mono>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-[2px] w-4 bg-[#ea580c]" />
          alarm <Mono className="text-[11px]">{alarmHigh.toFixed(0)}°C</Mono>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-[2px] w-4 bg-[#e5e5e5]" />
          setpoint <Mono className="text-[11px]">{setpoint.toFixed(0)}°C</Mono>
        </span>
        {firstBreachIndex > 0 ? (
          <span className="text-[#dc2626]">threshold crossed mid-window</span>
        ) : null}
        <span className="ml-auto">{readings.length} readings</span>
      </div>
    </div>
  );
}
