import { useState } from "react";
import { DisconnectedBanner } from "./components/DisconnectedBanner";
import { NavTabs } from "./components/NavTabs";
import type { ScreenId } from "./components/NavTabs";
import { AlarmsScreen } from "./screens/AlarmsScreen";
import { NowScreen } from "./screens/NowScreen";
import { RoutinesScreen } from "./screens/RoutinesScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { useAppState } from "./store/AppStore";

// docs/08-web-ui.md: "Night mode engaging during WINDDOWN/ASLEEP/SUNRISE:
// near-black, dim red-amber, no white, no animation." Driven purely by the
// server-reported routine state, never guessed client-side.
const NIGHT_STATES = new Set(["WINDDOWN", "ASLEEP", "SUNRISE"]);

export default function App(): JSX.Element {
  const { state, connected } = useAppState();
  const [screen, setScreen] = useState<ScreenId>("now");

  const isNight = state !== null && NIGHT_STATES.has(state.routine.state);
  const tz = state?.clock.tz ?? "UTC";

  return (
    <div className={`app${isNight ? " app--night" : ""}`}>
      <header className="app-header">
        <span className="wordmark">openrestore</span>
        <span
          className={`conn-dot${connected ? "" : " conn-dot--off"}`}
          role="status"
          aria-label={connected ? "connected" : "disconnected"}
          title={connected ? "connected" : "disconnected"}
        />
      </header>
      <DisconnectedBanner connected={connected} />
      {screen === "now" && <NowScreen state={state} />}
      {screen === "alarms" && <AlarmsScreen tz={tz} />}
      {screen === "routines" && <RoutinesScreen />}
      {screen === "settings" && <SettingsScreen tz={tz} />}
      <NavTabs active={screen} onChange={setScreen} />
    </div>
  );
}
