import React, { useState, useEffect, useRef } from "react";

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
            TRADINGVIEW
          </span>
        </div>
      </div>

      {/* Chart area */}
      <div style={{
        flex: 1, padding: 0,
        background: "#07091280",
        overflow: "hidden",
      }}>
        <iframe
          src="https://www.tradingview.com/widgetembed/?symbol=FX:EURUSD&interval=5&theme=dark&style=1&locale=en&toolbar_bg=0a0f1c&hide_side_toolbar=0&allow_symbol_change=1"
          width="100%"
          height="100%"
          frameBorder="0"
          allowTransparency="true"
        />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Agent Chat Panel
// ─────────────────────────────────────────────────────────────────────────────
function ChatPanel() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, thinking]);

  const handleSend = async () => {
    if (!input.trim() || thinking) return;

    const userMsg = input.trim();
    setMessages(prev => [...prev, { from: "user", text: userMsg }]);
    setInput("");
    setThinking(true);

    try {
      const response = await fetch("http://localhost:8000/backtest", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ strategy_code: userMsg }),
      });

      let nancyResponseText = "";
      if (!response.ok) {
        // Handle error by extracting detail if available
        const errData = await response.json().catch(() => null);
        nancyResponseText = "Error: " + (errData?.detail?.message || response.statusText || "Failed to communicate with Nancy.");
      } else {
        const data = await response.json();
        // Format the backtest result into a readable message
        nancyResponseText = "**" + data.strategy_name + "**\n\n" + data.summary + "\n\n**Verdict:** " + data.verdict + "\n\n**Reasoning:**\n" + data.reasoning;
        if (data.entry_conditions?.length) {
            nancyResponseText += "\n\n**Entries:**\n- " + data.entry_conditions.join('\n- ');
        }
        if (data.exit_conditions?.length) {
            nancyResponseText += "\n\n**Exits:**\n- " + data.exit_conditions.join('\n- ');
        }
      }

      setMessages(prev => [...prev, { from: "nancy", text: nancyResponseText }]);
    } catch (error) {
      console.error("Chat error:", error);
      setMessages(prev => [...prev, { from: "nancy", text: "Error: Could not connect to the backend server." }]);
    } finally {
      setThinking(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSend();
    }
  };

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
        {messages.map((msg, i) => {
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
                border: "1px solid " + (isNancy ? "#0d2a4a" : "#0d2a1f"),
                fontSize: 12,
                color: isNancy ? "#a0d0f0" : "#80c0a0",
                fontFamily: "monospace",
                lineHeight: 1.55,
                whiteSpace: "pre-wrap", // To respect newlines in Nancy's output
              }}>
                {msg.text}
              </div>
            </div>
          );
        })}
        
        {/* Thinking Indicator */}
        {thinking && (
          <div style={{
            display: "flex", flexDirection: "column",
            alignItems: "flex-start",
          }}>
            <span style={{
              fontSize: 9, color: "#2a4560",
              fontFamily: "monospace", marginBottom: 3,
              letterSpacing: "0.08em"
            }}>
              ◈ NANCY
            </span>
            <div style={{
                maxWidth: "85%", padding: "8px 12px", borderRadius: 3,
                background: "#0a1628", border: "1px solid #0d2a4a",
                fontSize: 12, color: "#00e5ff", fontFamily: "monospace",
                display: "flex", flexDirection: "column", gap: 6,
                minWidth: "120px"
              }}>
                <div style={{
                  height: "2px",
                  width: "100%",
                  background: "#00e5ff33",
                  borderRadius: "1px",
                  overflow: "hidden"
                }}>
                  <div style={{
                    height: "100%",
                    background: "#00e5ff",
                    width: "50%",
                    animation: "progressPulse 1.5s ease-in-out infinite alternate"
                  }} />
                </div>
                <span>Nancy is thinking...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input bar */}
      <div style={{
        padding: "10px 14px", borderTop: "1px solid #0d1f35",
        background: "#060a12", display: "flex", gap: 8, alignItems: "center"
      }}>
        <span style={{ color: "#00e5ff", fontFamily: "monospace", fontSize: 12 }}>›</span>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={thinking}
          placeholder="Ask Nancy something..."
          style={{
            flex: 1, fontSize: 12, color: "#e0f0ff",
            background: "transparent", border: "none", outline: "none",
            fontFamily: "monospace", letterSpacing: "0.04em"
          }}
        />
        <button
          onClick={handleSend}
          disabled={thinking || !input.trim()}
          style={{
            fontSize: 9, color: thinking || !input.trim() ? "#1a3050" : "#00e5ff", 
            fontFamily: "monospace", background: "transparent",
            border: "1px solid " + (thinking || !input.trim() ? "#1a3050" : "#00e5ff"), 
            padding: "2px 8px", borderRadius: 2, cursor: thinking || !input.trim() ? "not-allowed" : "pointer",
            transition: "all 0.2s"
          }}>
          ENTER
        </button>
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
            borderLeft: "2px solid " + LOG_COLORS[log.level] + "22",
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
              {"[" + log.level.toUpperCase().padEnd(7) + "]"}
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
      <style>{"* { box-sizing: border-box; margin: 0; padding: 0; } " +
        "body { background: #060a12; color: #e0f0ff; } " +
        "::-webkit-scrollbar { width: 4px; } " +
        "::-webkit-scrollbar-track { background: #060a12; } " +
        "::-webkit-scrollbar-thumb { background: #1a3050; border-radius: 2px; } " +
        "@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } } " +
        "@keyframes progressPulse { 0% { transform: translateX(-100%); opacity: 0.5; } 100% { transform: translateX(200%); opacity: 1; } }"
      }</style>

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

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
