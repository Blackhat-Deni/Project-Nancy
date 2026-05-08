import React, { useState, useEffect } from "react";

// ─── Hardcoded placeholder OHLC candlestick data ─────────────────────────────
const CANDLES = [
  { t: "09:00", o: 1.0820, h: 1.0855, l: 1.0810, c: 1.0845 },
  { t: "09:05", o: 1.0845, h: 1.0870, l: 1.0838, c: 1.0852 },
  { t: "09:10", o: 1.0852, h: 1.0860, l: 1.0820, c: 1.0825 },
  { t: "09:15", o: 1.0825, h: 1.0835, l: 1.0798, c: 1.0802 },
  { t: "09:20", o: 1.0802, h: 1.0830, l: 1.0795, c: 1.0828 },
  { t: "09:25", o: 1.0828, h: 1.0862, l: 1.0820, c: 1.0858 },
  { t: "09:30", o: 1.0858, h: 1.0875, l: 1.0845, c: 1.0848 },
  { t: "09:35", o: 1.0848, h: 1.0855, l: 1.0815, c: 1.0820 },
  { t: "09:40", o: 1.0820, h: 1.0840, l: 1.0808, c: 1.0835 },
  { t: "09:45", o: 1.0835, h: 1.0872, l: 1.0830, c: 1.0868 },
  { t: "09:50", o: 1.0868, h: 1.0880, l: 1.0855, c: 1.0862 },
  { t: "09:55", o: 1.0862, h: 1.0878, l: 1.0840, c: 1.0843 },
  { t: "10:00", o: 1.0843, h: 1.0850, l: 1.0812, c: 1.0818 },
  { t: "10:05", o: 1.0818, h: 1.0845, l: 1.0810, c: 1.0840 },
  { t: "10:10", o: 1.0840, h: 1.0865, l: 1.0835, c: 1.0860 },
];

// ─── Hardcoded placeholder chat messages ──────────────────────────────────────
const CHAT_MESSAGES = [
  { from: "user",  text: "Nancy, what's the current signal on EURUSD?" },
  { from: "nancy", text: "Signal is BULLISH. RSI at 58.4, MACD crossed positive. Watching 1.0875 resistance." },
  { from: "user",  text: "What's the recommended position size?" },
  { from: "nancy", text: "Based on 1% risk and current ATR, recommended size is 0.12 lots. Stop at 1.0812." },
  { from: "user",  text: "Any news events to watch today?" },
  { from: "nancy", text: "EUR CPI at 10:30 UTC. High impact. Suggest reducing exposure 5 minutes prior." },
];

// ─── Hardcoded placeholder log entries ───────────────────────────────────────
const LOGS = [
  { level: "info",    time: "10:10:02", msg: "Market data stream connected — EURUSD" },
  { level: "info",    time: "10:10:05", msg: "Strategy loaded: RSI_MACD_Breakout v2" },
  { level: "info",    time: "10:10:12", msg: "Signal evaluated — direction: BUY" },
  { level: "warning", time: "10:10:18", msg: "Spread widened to 2.4 pips — pausing entry" },
  { level: "info",    time: "10:10:25", msg: "Spread normalized — resuming scan" },
  { level: "info",    time: "10:10:31", msg: "Order queued: BUY 0.12 EURUSD @ 1.0840" },
  { level: "error",   time: "10:10:33", msg: "Broker connection timeout — retrying..." },
  { level: "info",    time: "10:10:35", msg: "Broker reconnected successfully" },
  { level: "info",    time: "10:10:40", msg: "Order placed: ID #NX-00412" },
  { level: "info",    time: "10:10:55", msg: "Trade monitoring active — SL: 1.0812 | TP: 1.0892" },
];

// ─── Colour & type token map for log levels ───────────────────────────────────
const LOG_COLORS = { info: "#00e5ff", warning: "#ffdd57", error: "#ff3860" };
const LOG_ICONS  = { info: "●", warning: "▲", error: "✖" };

// ─────────────────────────────────────────────────────────────────────────────
// SVG Candlestick Chart
// ─────────────────────────────────────────────────────────────────────────────
function CandlestickChart() {
  const W = 820, H = 320;
  const PAD = { top: 20, right: 20, bottom: 36, left: 58 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;

  // Calculate price range across all candles
  const allPrices = CANDLES.flatMap(c => [c.h, c.l]);
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const priceRange = maxP - minP;
  const padP = priceRange * 0.1;

  // Map a price value to a Y pixel coordinate
  const toY = p =>
    PAD.top + chartH - ((p - (minP - padP)) / (priceRange + padP * 2)) * chartH;

  // Map a candle index to an X pixel coordinate (centred)
  const candleSlot = chartW / CANDLES.length;
  const toX = i => PAD.left + i * candleSlot + candleSlot / 2;
  const candleW = candleSlot * 0.55;

  // Build horizontal price grid lines
  const gridCount = 5;
  const gridLines = Array.from({ length: gridCount + 1 }, (_, i) => {
    const price = (minP - padP) + ((priceRange + padP * 2) / gridCount) * i;
    return { y: toY(price), label: price.toFixed(4) };
  });

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }}>
      {/* Chart background */}
      <rect x={PAD.left} y={PAD.top} width={chartW} height={chartH}
        fill="#0a0e1a" rx="2" />

      {/* Horizontal grid lines */}
      {gridLines.map((g, i) => (
        <g key={i}>
          <line x1={PAD.left} y1={g.y} x2={PAD.left + chartW} y2={g.y}
            stroke="#1e2a3a" strokeWidth="1" strokeDasharray="4,4" />
          <text x={PAD.left - 6} y={g.y + 4} fill="#4a6080" fontSize="10"
            fontFamily="'Courier New', monospace" textAnchor="end">
            {g.label}
          </text>
        </g>
      ))}

      {/* Candle sticks */}
      {CANDLES.map((c, i) => {
        const x     = toX(i);
        const isBull = c.c >= c.o;
        const color  = isBull ? "#00e5a0" : "#ff3860";
        const bodyTop = toY(Math.max(c.o, c.c));
        const bodyBot = toY(Math.min(c.o, c.c));
        const bodyH   = Math.max(bodyBot - bodyTop, 1);

        return (
          <g key={i}>
            {/* High-low wick */}
            <line x1={x} y1={toY(c.h)} x2={x} y2={toY(c.l)}
              stroke={color} strokeWidth="1.5" />
            {/* Body */}
            <rect x={x - candleW / 2} y={bodyTop} width={candleW} height={bodyH}
              fill={isBull ? color : "transparent"}
              stroke={color} strokeWidth="1.5" />
          </g>
        );
      })}

      {/* X-axis time labels */}
      {CANDLES.map((c, i) => (
        i % 3 === 0 && (
          <text key={i} x={toX(i)} y={H - 8} fill="#4a6080" fontSize="10"
            fontFamily="'Courier New', monospace" textAnchor="middle">
            {c.t}
          </text>
        )
      ))}

      {/* Axis border lines */}
      <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top + chartH}
        stroke="#1e3050" strokeWidth="1" />
      <line x1={PAD.left} y1={PAD.top + chartH} x2={PAD.left + chartW}
        y2={PAD.top + chartH} stroke="#1e3050" strokeWidth="1" />
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Top Navigation Bar
// ─────────────────────────────────────────────────────────────────────────────
function TopBar({ time }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "0 24px", height: 52,
      background: "#060a12",
      borderBottom: "1px solid #0d1f35",
      flexShrink: 0,
    }}>
      {/* Logo + brand */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span style={{
          fontSize: 18, fontWeight: 800, letterSpacing: "0.12em",
          color: "#00e5ff", fontFamily: "'Courier New', monospace"
        }}>
          PROJECT NANCY
        </span>
        <span style={{
          fontSize: 11, color: "#2a4560",
          fontFamily: "'Courier New', monospace", letterSpacing: "0.1em"
        }}>
          v0.1.0
        </span>
      </div>

      {/* Centre — pair + spread */}
      <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#3a5570", fontFamily: "monospace", letterSpacing: "0.12em" }}>
            PAIR
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#e0f0ff", fontFamily: "monospace", letterSpacing: "0.08em" }}>
            EUR/USD
          </div>
        </div>
        <div style={{ width: 1, height: 28, background: "#0d1f35" }} />
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#3a5570", fontFamily: "monospace", letterSpacing: "0.12em" }}>PRICE</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#00e5a0", fontFamily: "monospace" }}>1.0860</div>
        </div>
        <div style={{ width: 1, height: 28, background: "#0d1f35" }} />
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#3a5570", fontFamily: "monospace", letterSpacing: "0.12em" }}>SPREAD</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#ffdd57", fontFamily: "monospace" }}>1.2</div>
        </div>
      </div>

      {/* Right — agent status + clock */}
      <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
        {/* Agent status pill */}
        <div style={{
          display: "flex", alignItems: "center", gap: 7,
          padding: "4px 12px", borderRadius: 3,
          background: "#001a0e", border: "1px solid #00e5a030",
        }}>
          <span style={{
            width: 7, height: 7, borderRadius: "50%",
            background: "#00e5a0",
            boxShadow: "0 0 6px #00e5a0",
            display: "inline-block",
            animation: "pulse 2s infinite",
          }} />
          <span style={{
            fontSize: 11, fontWeight: 700, color: "#00e5a0",
            fontFamily: "'Courier New', monospace", letterSpacing: "0.12em"
          }}>
            NANCY ONLINE
          </span>
        </div>

        {/* Live clock */}
        <div style={{
          fontSize: 13, color: "#4a7090",
          fontFamily: "'Courier New', monospace", letterSpacing: "0.08em"
        }}>
          {time}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart Panel (left 70%)
// ─────────────────────────────────────────────────────────────────────────────
function ChartPanel() {
  return (
    <div style={{
      flex: "0 0 70%", display: "flex", flexDirection: "column",
      borderRight: "1px solid #0d1f35", overflow: "hidden",
    }}>
      {/* Panel header */}
      <div style={{
        padding: "10px 18px", borderBottom: "1px solid #0d1f35",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        background: "#080c18",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            fontSize: 11, fontWeight: 700, color: "#00e5ff",
            fontFamily: "monospace", letterSpacing: "0.12em"
          }}>
            EURUSD · M5
          </span>
          <span style={{
            fontSize: 10, color: "#2a4560",
            fontFamily: "monospace", padding: "2px 6px",
            border: "1px solid #0d1f35", borderRadius: 2
          }}>
            CANDLESTICK
          </span>
        </div>
        <div style={{ display: "flex", gap: 14 }}>
          {["M1","M5","M15","H1","H4","D1"].map(tf => (
            <span key={tf} style={{
              fontSize: 10, color: tf === "M5" ? "#00e5ff" : "#2a4560",
              fontFamily: "monospace", cursor: "pointer",
              borderBottom: tf === "M5" ? "1px solid #00e5ff" : "none",
              paddingBottom: 1,
            }}>
              {tf}
            </span>
          ))}
        </div>
      </div>

      {/* Chart area */}
      <div style={{
        flex: 1, padding: "16px 12px 8px",
        background: "#07091280",
        overflow: "hidden",
      }}>
        <CandlestickChart />
      </div>

      {/* Stats row below chart */}
      <div style={{
        display: "flex", gap: 0,
        borderTop: "1px solid #0d1f35",
        background: "#060a12",
      }}>
        {[
          { label: "OPEN",  value: "1.0840", color: "#e0f0ff" },
          { label: "HIGH",  value: "1.0880", color: "#00e5a0" },
          { label: "LOW",   value: "1.0795", color: "#ff3860" },
          { label: "CLOSE", value: "1.0860", color: "#e0f0ff" },
          { label: "VOL",   value: "24,812", color: "#00e5ff"  },
          { label: "ATR",   value: "0.0042", color: "#ffdd57"  },
        ].map((s, i) => (
          <div key={i} style={{
            flex: 1, padding: "8px 12px",
            borderRight: i < 5 ? "1px solid #0d1f35" : "none",
          }}>
            <div style={{ fontSize: 9, color: "#2a4560", fontFamily: "monospace", letterSpacing: "0.1em" }}>
              {s.label}
            </div>
            <div style={{ fontSize: 13, color: s.color, fontFamily: "monospace", fontWeight: 600, marginTop: 2 }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Agent Chat Panel
// ─────────────────────────────────────────────────────────────────────────────
function ChatPanel() {
  return (
    <div style={{
      flex: 1, display: "flex", flexDirection: "column",
      borderBottom: "1px solid #0d1f35", overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "10px 16px", borderBottom: "1px solid #0d1f35",
        background: "#080c18", display: "flex", alignItems: "center", gap: 8
      }}>
        <span style={{ fontSize: 11, color: "#00e5ff", fontFamily: "monospace", letterSpacing: "0.12em", fontWeight: 700 }}>
          AGENT CHAT
        </span>
        <span style={{ fontSize: 9, color: "#2a4560", fontFamily: "monospace" }}>
          — NANCY
        </span>
      </div>

      {/* Messages */}
      <div style={{
        flex: 1, overflowY: "auto", padding: "12px 14px",
        display: "flex", flexDirection: "column", gap: 10,
        background: "#07091200",
      }}>
        {CHAT_MESSAGES.map((msg, i) => {
          const isNancy = msg.from === "nancy";
          return (
            <div key={i} style={{
              display: "flex", flexDirection: "column",
              alignItems: isNancy ? "flex-start" : "flex-end",
            }}>
              <span style={{
                fontSize: 9, color: "#2a4560",
                fontFamily: "monospace", marginBottom: 3,
                letterSpacing: "0.08em"
              }}>
                {isNancy ? "◈ NANCY" : "YOU"}
              </span>
              <div style={{
                maxWidth: "85%", padding: "8px 12px", borderRadius: 3,
                background: isNancy ? "#0a1628" : "#091820",
                border: `1px solid ${isNancy ? "#0d2a4a" : "#0d2a1f"}`,
                fontSize: 12,
                color: isNancy ? "#a0d0f0" : "#80c0a0",
                fontFamily: "monospace",
                lineHeight: 1.55,
              }}>
                {msg.text}
              </div>
            </div>
          );
        })}
      </div>

      {/* Input bar placeholder */}
      <div style={{
        padding: "10px 14px", borderTop: "1px solid #0d1f35",
        background: "#060a12", display: "flex", gap: 8, alignItems: "center"
      }}>
        <span style={{ color: "#00e5ff", fontFamily: "monospace", fontSize: 12 }}>›</span>
        <div style={{
          flex: 1, fontSize: 12, color: "#2a4560",
          fontFamily: "monospace", letterSpacing: "0.04em"
        }}>
          Ask Nancy something...
        </div>
        <div style={{
          fontSize: 9, color: "#1a3050", fontFamily: "monospace",
          border: "1px solid #1a3050", padding: "2px 8px", borderRadius: 2
        }}>
          ENTER
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Live Log Stream Panel
// ─────────────────────────────────────────────────────────────────────────────
function LogPanel() {
  return (
    <div style={{
      flex: 1, display: "flex", flexDirection: "column", overflow: "hidden"
    }}>
      {/* Header */}
      <div style={{
        padding: "10px 16px", borderBottom: "1px solid #0d1f35",
        background: "#080c18", display: "flex", alignItems: "center", justifyContent: "space-between"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "#00e5ff", fontFamily: "monospace", letterSpacing: "0.12em", fontWeight: 700 }}>
            LIVE LOG STREAM
          </span>
        </div>
        {/* Blinking live indicator */}
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span style={{
            width: 6, height: 6, borderRadius: "50%", background: "#ff3860",
            display: "inline-block", boxShadow: "0 0 5px #ff3860",
          }} />
          <span style={{ fontSize: 9, color: "#ff3860", fontFamily: "monospace", letterSpacing: "0.1em" }}>
            LIVE
          </span>
        </div>
      </div>

      {/* Log entries */}
      <div style={{
        flex: 1, overflowY: "auto", padding: "8px 4px",
        fontFamily: "'Courier New', monospace", fontSize: 11,
      }}>
        {LOGS.map((log, i) => (
          <div key={i} style={{
            display: "flex", alignItems: "flex-start", gap: 8,
            padding: "5px 12px",
            borderLeft: `2px solid ${LOG_COLORS[log.level]}22`,
            marginBottom: 1,
            background: i % 2 === 0 ? "#07091208" : "transparent",
          }}>
            {/* Level icon */}
            <span style={{ color: LOG_COLORS[log.level], fontSize: 9, marginTop: 1, flexShrink: 0 }}>
              {LOG_ICONS[log.level]}
            </span>
            {/* Timestamp */}
            <span style={{ color: "#2a4560", flexShrink: 0, fontSize: 10 }}>
              {log.time}
            </span>
            {/* Level badge */}
            <span style={{
              color: LOG_COLORS[log.level], flexShrink: 0,
              fontSize: 9, letterSpacing: "0.1em", width: 52,
            }}>
              [{log.level.toUpperCase().padEnd(7)}]
            </span>
            {/* Message */}
            <span style={{ color: "#5a8090", lineHeight: 1.4 }}>
              {log.msg}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Right Sidebar — stacked Chat + Logs
// ─────────────────────────────────────────────────────────────────────────────
function RightSidebar() {
  return (
    <div style={{
      flex: "0 0 30%", display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      <ChatPanel />
      <LogPanel />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Root App Component
// ─────────────────────────────────────────────────────────────────────────────
export default function App() {
  // Live clock — updates every second
  const [time, setTime] = useState(() => new Date().toLocaleTimeString("en-GB", { hour12: false }));

  useEffect(() => {
    const timer = setInterval(() => {
      setTime(new Date().toLocaleTimeString("en-GB", { hour12: false }));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <>
      {/* Global style reset and body override */}
      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #060a12; color: #e0f0ff; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #060a12; }
        ::-webkit-scrollbar-thumb { background: #1a3050; border-radius: 2px; }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>

      {/* Full-height app shell */}
      <div style={{
        display: "flex", flexDirection: "column",
        height: "100vh", width: "100vw",
        background: "#060a12", overflow: "hidden",
        fontFamily: "'Courier New', monospace",
      }}>
        {/* Top bar with agent status and live clock */}
        <TopBar time={time} />

        {/* Main content — 70/30 horizontal split */}
        <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
          <ChartPanel />
          <RightSidebar />
        </div>
      </div>
    </>
  );
}
