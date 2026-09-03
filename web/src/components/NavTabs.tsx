export type ScreenId = "now" | "alarms" | "routines" | "settings";

const TABS: { id: ScreenId; label: string }[] = [
  { id: "now", label: "Now" },
  { id: "alarms", label: "Alarms" },
  { id: "routines", label: "Routines" },
  { id: "settings", label: "Settings" },
];

export function NavTabs({
  active,
  onChange,
}: {
  active: ScreenId;
  onChange: (screen: ScreenId) => void;
}): JSX.Element {
  return (
    <nav className="nav" aria-label="Screens">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`nav-item${tab.id === active ? " nav-item--active" : ""}`}
          aria-current={tab.id === active ? "page" : undefined}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
