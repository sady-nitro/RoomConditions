import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type ChartKey = "temperature" | "humidity" | "pressure";

type Measurement = {
  id: string;
  timestamp: Date;
  label: string;
  dateLabel: string;
  hourLabel: string;
  temperature: number;
  humidity: number;
  pressure: number;
};

const SERIES: {
  key: ChartKey;
  label: string;
  unit: string;
  color: string;
}[] = [
  { key: "temperature", label: "気温", unit: "°C", color: "#f59e0b" },
  { key: "humidity", label: "湿度", unit: "%", color: "#38bdf8" },
  { key: "pressure", label: "気圧", unit: "hPa", color: "#a78bfa" },
];

const formatTimestamp = (date: Date) =>
  `${String(date.getMonth() + 1).padStart(2, "0")}/${String(
    date.getDate(),
  ).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(
    date.getMinutes(),
  ).padStart(2, "0")}`;

function parseMeasurements(source: string): Measurement[] {
  const lines = source
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (lines.length === 0) {
    throw new Error("計測データがありません。");
  }

  const rows = lines.map((line, index) => {
    const [
      dateText,
      hourText,
      temperatureText,
      humidityText,
      pressureText,
    ] = line.split(",").map((value) => value.trim());
    const hour = Number(hourText);
    const timestamp = new Date(
      `${dateText}T${String(hour).padStart(2, "0")}:00:00`,
    );
    const temperature = Number(temperatureText);
    const humidity = Number(humidityText);
    const pressure = Number(pressureText);

    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(dateText) ||
      !Number.isInteger(hour) ||
      hour < 0 ||
      hour > 23 ||
      Number.isNaN(timestamp.getTime()) ||
      ![temperature, humidity, pressure].every(Number.isFinite)
    ) {
      throw new Error(`${index + 1}行目の形式が正しくありません。`);
    }

    return {
      id: `measurement-${index}`,
      timestamp,
      label: formatTimestamp(timestamp),
      dateLabel: dateText.replaceAll("-", "/"),
      hourLabel: String(hour).padStart(2, "0"),
      temperature,
      humidity,
      pressure,
    };
  });

  return rows.sort(
    (left, right) => left.timestamp.getTime() - right.timestamp.getTime(),
  );
}

function MetricIcon({ type }: { type: ChartKey }) {
  if (type === "temperature") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0Z" />
      </svg>
    );
  }

  if (type === "humidity") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m12 2.69 5.66 5.66a8 8 0 1 1-11.31 0Z" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 8v4l3 3" />
    </svg>
  );
}

function CurrentCard({
  label,
  value,
  unit,
  color,
  icon,
}: {
  label: string;
  value: number;
  unit: string;
  color: string;
  icon: ReactNode;
}) {
  return (
    <article
      className="metric-card"
      style={{ "--metric-color": color } as CSSProperties}
    >
      <div className="metric-card__header">
        <span>{label}</span>
        <span className="metric-card__icon">{icon}</span>
      </div>
      <div className="metric-card__value">
        <strong>{value.toFixed(1)}</strong>
        <span>{unit}</span>
      </div>
      <div className="metric-card__rule" />
    </article>
  );
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{
    color: string;
    dataKey: ChartKey;
    name: string;
    value: number;
  }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;

  return (
    <div className="chart-tooltip">
      <p>{label}</p>
      {payload.map((item) => {
        const series = SERIES.find(({ key }) => key === item.dataKey);
        return (
          <div key={item.dataKey} style={{ color: item.color }}>
            {item.name}: <strong>{item.value}</strong> {series?.unit}
          </div>
        );
      })}
    </div>
  );
}

function ChartXAxisTick({
  x = 0,
  y = 0,
  payload,
  measurements,
}: {
  x?: number;
  y?: number;
  payload?: { value: string };
  measurements: Measurement[];
}) {
  const measurement = measurements.find(({ id }) => id === payload?.value);

  if (!measurement) return null;

  return (
    <g transform={`translate(${x},${y})`}>
      <text
        textAnchor="middle"
        fill="#5a7090"
        fontSize={10}
        fontFamily="'JetBrains Mono', monospace"
      >
        <tspan x="0" dy="12">
          {measurement.timestamp.getMonth() + 1}/
          {measurement.timestamp.getDate()}
        </tspan>
        <tspan x="0" dy="13">
          {String(measurement.timestamp.getHours()).padStart(2, "0")}
        </tspan>
      </text>
    </g>
  );
}

export default function App() {
  const [measurements, setMeasurements] = useState<Measurement[]>([]);
  const [currentMeasurement, setCurrentMeasurement] =
    useState<Measurement | null>(null);
  const [error, setError] = useState("");
  const [now] = useState(() => new Date());
  const [chartWidth, setChartWidth] = useState(320);
  const chartFrameRef = useRef<HTMLDivElement>(null);
  const [activeKeys, setActiveKeys] = useState<ChartKey[]>([
    "temperature",
    "humidity",
    "pressure",
  ]);

  useEffect(() => {
    const controller = new AbortController();

    Promise.all([
      fetch(`${import.meta.env.BASE_URL}data/data.csv`, {
        signal: controller.signal,
      }).then((response) => {
        if (!response.ok) {
          throw new Error(`計測データを読み込めませんでした (${response.status})。`);
        }
        return response.text();
      }),
      fetch("/api/current-measurement", {
        signal: controller.signal,
        cache: "no-store",
      }).then((response) => {
        if (!response.ok) {
          throw new Error(`現在の計測値を取得できませんでした (${response.status})。`);
        }
        return response.text();
      }),
    ])
      .then(([historyText, currentText]) => {
        const currentRows = parseMeasurements(currentText);
        setMeasurements(parseMeasurements(historyText));
        setCurrentMeasurement(currentRows.at(-1) ?? null);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(
          reason instanceof Error
            ? reason.message
            : "計測データの読み込みに失敗しました。",
        );
      });

    return () => controller.abort();
  }, []);

  useEffect(() => {
    const chartFrame = chartFrameRef.current;
    if (!chartFrame) return;

    const updateWidth = () => setChartWidth(chartFrame.clientWidth);
    const resizeObserver = new ResizeObserver(updateWidth);

    updateWidth();
    resizeObserver.observe(chartFrame);

    return () => resizeObserver.disconnect();
  }, [measurements.length]);

  const current = currentMeasurement;
  const latest24 = useMemo(() => measurements.slice(-24), [measurements]);
  const latest48 = useMemo(() => measurements.slice(-48), [measurements]);
  const chartTicks = useMemo(() => {
    if (latest48.length < 2) return latest48.map(({ id }) => id);

    const plotWidth = Math.max(chartWidth - 110, 1);
    const pixelsPerDataPoint = plotWidth / (latest48.length - 1);
    const tickStep = Math.max(1, Math.ceil(30 / pixelsPerDataPoint));

    return latest48
      .filter((_, index) => index % tickStep === 0)
      .map(({ id }) => id);
  }, [chartWidth, latest48]);

  const toggleKey = (key: ChartKey) => {
    setActiveKeys((currentKeys) =>
      currentKeys.includes(key)
        ? currentKeys.filter((currentKey) => currentKey !== key)
        : [...currentKeys, key],
    );
  };

  if (error || !current) {
    return (
      <main className="status-screen">
        <div className={`status-box${error ? " status-box--error" : ""}`}>
          <span className="status-dot" />
          {error || "計測データを読み込んでいます…"}
        </div>
      </main>
    );
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div className="brand">
          <span className="brand__dot" />
          <h1>Room Conditions</h1>
        </div>
        <time dateTime={now.toISOString()}>{formatTimestamp(now)}</time>
      </header>

      <main className="dashboard-main">
        <section>
          <h2 className="section-title">現在の計測値</h2>
          <div className="metric-grid">
            <CurrentCard
              label="気温"
              value={current.temperature}
              unit="°C"
              color="#f59e0b"
              icon={<MetricIcon type="temperature" />}
            />
            <CurrentCard
              label="湿度"
              value={current.humidity}
              unit="%"
              color="#38bdf8"
              icon={<MetricIcon type="humidity" />}
            />
            <CurrentCard
              label="気圧"
              value={current.pressure}
              unit="hPa"
              color="#a78bfa"
              icon={<MetricIcon type="pressure" />}
            />
          </div>
        </section>

        <section>
          <h2 className="section-title">過去24時間 — 時間帯別計測値</h2>
          <div className="table-frame">
            <table>
              <thead>
                <tr>
                  <th>日付</th>
                  <th>時間帯</th>
                  <th className="temperature">気温</th>
                  <th className="humidity">湿度</th>
                  <th className="pressure">気圧</th>
                </tr>
              </thead>
              <tbody>
                {[...latest24].reverse().map((row, index) => (
                  <tr key={row.id} className={index === 0 ? "is-latest" : ""}>
                    <td>
                      {row.dateLabel}
                      {index === 0 && <span className="latest-badge">最新</span>}
                    </td>
                    <td>{row.hourLabel}</td>
                    <td className="temperature">{row.temperature.toFixed(1)}</td>
                    <td className="humidity">{row.humidity.toFixed(1)}</td>
                    <td className="pressure">{row.pressure.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <div className="chart-heading">
            <h2 className="section-title">過去48時間 — トレンドグラフ</h2>
            <div className="series-controls" aria-label="グラフ表示項目">
              {SERIES.map((series) => {
                const isActive = activeKeys.includes(series.key);
                return (
                  <button
                    key={series.key}
                    type="button"
                    aria-pressed={isActive}
                    onClick={() => toggleKey(series.key)}
                    style={
                      {
                        "--series-color": series.color,
                      } as CSSProperties
                    }
                  >
                    {series.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="chart-frame" ref={chartFrameRef}>
            <ResponsiveContainer width="100%" height={360}>
              <LineChart
                data={latest48}
                margin={{ top: 8, right: 16, left: 0, bottom: 12 }}
              >
                <CartesianGrid
                  strokeDasharray="2 4"
                  stroke="#38bdf80a"
                  vertical={false}
                />
                <XAxis
                  dataKey="id"
                  ticks={chartTicks}
                  tick={<ChartXAxisTick measurements={latest48} />}
                  tickLine={false}
                  axisLine={{ stroke: "#38bdf815" }}
                  interval={0}
                  height={38}
                />
                <YAxis
                  yAxisId="left"
                  tick={{
                    fontSize: 10,
                    fill: "#5a7090",
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                  tickLine={false}
                  axisLine={false}
                  width={42}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  domain={["auto", "auto"]}
                  tick={{
                    fontSize: 10,
                    fill: "#a78bfa",
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                  tickLine={false}
                  axisLine={false}
                  width={52}
                />
                <Tooltip content={<ChartTooltip />} />
                <Legend
                  wrapperStyle={{
                    fontSize: "11px",
                    fontFamily: "'JetBrains Mono', monospace",
                    color: "#5a7090",
                    paddingTop: "12px",
                  }}
                />
                {activeKeys.includes("temperature") && (
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="temperature"
                    name="気温"
                    stroke="#f59e0b"
                    strokeWidth={1.5}
                    dot={false}
                    activeDot={{ r: 3, fill: "#f59e0b" }}
                  />
                )}
                {activeKeys.includes("humidity") && (
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="humidity"
                    name="湿度"
                    stroke="#38bdf8"
                    strokeWidth={1.5}
                    dot={false}
                    activeDot={{ r: 3, fill: "#38bdf8" }}
                  />
                )}
                {activeKeys.includes("pressure") && (
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="pressure"
                    name="気圧"
                    stroke="#a78bfa"
                    strokeWidth={1.5}
                    dot={false}
                    activeDot={{ r: 3, fill: "#a78bfa" }}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      </main>

      <footer>Room Conditions copyright @ 2026 sady_nitro. All rights reserved.</footer>
    </div>
  );
}
